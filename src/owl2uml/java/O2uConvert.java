// Convert one ontology document to Turtle with the OWL API bundled in robot.jar.
//
// Usage: java -cp robot.jar[:dir] O2uConvert <syntax> <input> <output.ttl> [IRI=FILE ...]
//   syntax: owx | omn | ofn | obo | rdfxml | ttl
//   IRI=FILE: a local RDF/XML copy of an import, already resolved by owl2uml.
//     Manchester needs these: it rejects names that are declared only in an
//     imported ontology.
//
// Unlike `robot convert` this
//   * uses only the parser for the given syntax, so a broken Manchester file
//     is reported as a Manchester error (the OBO parser otherwise accepts
//     almost anything and the run "succeeds" with junk);
//   * never fetches owl:imports: an import IRI maps to its IRI=FILE copy or
//     else to an empty stub, and the imports declarations are kept so that
//     owl2uml resolves them itself (catalog, local directory, network).
// On failure it prints "O2U-ERROR: <message>" to stderr and exits 2.
import java.io.File;

import org.semanticweb.owlapi.apibinding.OWLManager;
import org.semanticweb.owlapi.formats.PrefixDocumentFormat;
import org.semanticweb.owlapi.formats.TurtleDocumentFormat;
import org.semanticweb.owlapi.io.FileDocumentSource;
import org.semanticweb.owlapi.io.OWLParserFactory;
import org.semanticweb.owlapi.model.IRI;
import org.semanticweb.owlapi.model.MissingImportHandlingStrategy;
import org.semanticweb.owlapi.model.OWLDocumentFormat;
import org.semanticweb.owlapi.model.OWLOntology;
import org.semanticweb.owlapi.model.OWLOntologyLoaderConfiguration;
import org.semanticweb.owlapi.model.OWLOntologyManager;

public class O2uConvert {
    static OWLParserFactory parser(String syntax) {
        switch (syntax) {
            case "owx": return new org.semanticweb.owlapi.owlxml.parser.OWLXMLParserFactory();
            case "omn": return new org.semanticweb.owlapi.manchestersyntax.parser.ManchesterOWLSyntaxOntologyParserFactory();
            case "ofn": return new org.semanticweb.owlapi.functional.parser.OWLFunctionalSyntaxOWLParserFactory();
            case "obo": return new org.semanticweb.owlapi.oboformat.OBOFormatOWLAPIParserFactory();
            case "rdfxml": return new org.semanticweb.owlapi.rdf.rdfxml.parser.RDFXMLParserFactory();
            case "ttl": return new org.semanticweb.owlapi.rdf.turtle.parser.TurtleOntologyParserFactory();
            default: throw new IllegalArgumentException("unknown syntax: " + syntax);
        }
    }

    static OWLDocumentFormat format(String syntax) {
        switch (syntax) {
            case "owx": return new org.semanticweb.owlapi.formats.OWLXMLDocumentFormat();
            case "omn": return new org.semanticweb.owlapi.formats.ManchesterSyntaxDocumentFormat();
            case "ofn": return new org.semanticweb.owlapi.formats.FunctionalSyntaxDocumentFormat();
            case "obo": return new org.semanticweb.owlapi.formats.OBODocumentFormat();
            case "rdfxml": return new org.semanticweb.owlapi.formats.RDFXMLDocumentFormat();
            default: return new TurtleDocumentFormat();
        }
    }

    static String stubText(String syntax) {
        switch (syntax) {
            case "owx": return "<?xml version=\"1.0\"?>\n<Ontology xmlns=\"http://www.w3.org/2002/07/owl#\"/>\n";
            case "omn": return "Prefix: : <urn:o2u:stub#>\nOntology: <urn:o2u:stub>\n";
            case "ofn": return "Ontology(<urn:o2u:stub>)\n";
            case "obo": return "format-version: 1.2\n";
            case "rdfxml": return "<?xml version=\"1.0\"?>\n<rdf:RDF xmlns:rdf=\"http://www.w3.org/1999/02/22-rdf-syntax-ns#\"/>\n";
            default: return "";
        }
    }

    public static void main(String[] args) {
        if (args.length < 3) {
            System.err.println("O2U-ERROR: usage: O2uConvert <syntax> <input> <output.ttl> [IRI=FILE ...]");
            System.exit(2);
        }
        final java.util.Map<IRI, IRI> local = new java.util.HashMap<>();
        for (int i = 3; i < args.length; i++) {
            int eq = args[i].indexOf('=');
            local.put(IRI.create(args[i].substring(0, eq)),
                      IRI.create(new File(args[i].substring(eq + 1))));
        }
        try {
            OWLOntologyManager m = OWLManager.createOWLOntologyManager();
            java.util.Set<OWLParserFactory> parsers = new java.util.HashSet<>();
            parsers.add(parser(args[0]));
            if (!local.isEmpty() && !args[0].equals("rdfxml")) {
                parsers.add(parser("rdfxml"));   // the IRI=FILE copies
            }
            m.setOntologyParsers(parsers);
            // An import without a local copy resolves to an empty stub ontology
            // in the same syntax. Some parsers, e.g. Manchester, dereference the
            // imported ontology while parsing, so a missing one is not enough;
            // the stub declares a prefix because the Manchester parser adopts
            // the imported document's prefixes.
            File stub = File.createTempFile("o2u-stub", "." + args[0]);
            stub.deleteOnExit();
            java.nio.file.Files.write(stub.toPath(),
                    stubText(args[0]).getBytes(java.nio.charset.StandardCharsets.UTF_8));
            final IRI stubIri = IRI.create(stub);
            m.getIRIMappers().set(iri -> local.getOrDefault(iri, stubIri));
            OWLOntologyLoaderConfiguration cfg = new OWLOntologyLoaderConfiguration()
                    .setMissingImportHandlingStrategy(MissingImportHandlingStrategy.SILENT);
            File input = new File(args[1]);
            if (args[0].equals("omn")) {
                // Manchester checks every name against the ontologies already in
                // the manager, so load the import copies first.
                for (IRI copy : new java.util.HashSet<>(local.values())) {
                    m.loadOntologyFromOntologyDocument(
                            new FileDocumentSource(new File(copy.toURI()), format("rdfxml")), cfg);
                }
            }
            OWLOntology ont = m.loadOntologyFromOntologyDocument(
                    new FileDocumentSource(input, format(args[0])), cfg);
            TurtleDocumentFormat out = new TurtleDocumentFormat();
            OWLDocumentFormat in = m.getOntologyFormat(ont);
            if (in instanceof PrefixDocumentFormat) {
                out.copyPrefixesFrom((PrefixDocumentFormat) in);
            }
            m.saveOntology(ont, out, IRI.create(new File(args[2])));
        } catch (Throwable e) {
            if (System.getenv("O2U_DEBUG") != null) e.printStackTrace();
            String msg = String.valueOf(e.getMessage()).trim();
            System.err.println("O2U-ERROR: " + msg);
            System.exit(2);
        }
    }
}
