// One justification per entailment, with the OWL API, HermiT and the
// owlexplanation library bundled in robot.jar. Used by `owl2uml claims`.
//
// Usage: java -cp robot.jar[:dir] O2uExplain <ontology> <queries.txt> <out.txt>
//   ontology:    any syntax the OWL API reads (owl2uml passes N-Triples)
//   queries.txt: one query per line, "<id>\t<axiom in Functional syntax>",
//                full IRIs in angle brackets, e.g.
//                c0001\tSubClassOf(<http://ex/A> <http://ex/B>)
//                The id "!inconsistent" asks why the ontology is inconsistent.
//
// Output, per query:
//   @@ENTRY\t<id>\t<n>     n = number of axioms in the justification,
//                          -1 = not entailed, -2 = query could not be parsed
//   @@AXIOM                followed by the axiom as a one-axiom Turtle document
//   ...
//   @@END
//
// The axioms are written as Turtle so that owl2uml can give them the same
// stable ids (axioms.py) as the axioms of the ontology it loaded with rdflib.
// One JVM answers every query; owl2uml caps the number of queries.
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.PrintWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.List;
import java.util.Set;

import org.semanticweb.HermiT.ReasonerFactory;
import org.semanticweb.owl.explanation.api.Explanation;
import org.semanticweb.owl.explanation.api.ExplanationGenerator;
import org.semanticweb.owl.explanation.api.ExplanationGeneratorFactory;
import org.semanticweb.owl.explanation.api.ExplanationManager;
import org.semanticweb.owl.explanation.impl.blackbox.checker.InconsistentOntologyExplanationGeneratorFactory;
import org.semanticweb.owlapi.apibinding.OWLManager;
import org.semanticweb.owlapi.formats.TurtleDocumentFormat;
import org.semanticweb.owlapi.io.StringDocumentSource;
import org.semanticweb.owlapi.model.IRI;
import org.semanticweb.owlapi.model.MissingImportHandlingStrategy;
import org.semanticweb.owlapi.model.OWLAxiom;
import org.semanticweb.owlapi.model.OWLDataFactory;
import org.semanticweb.owlapi.model.OWLOntology;
import org.semanticweb.owlapi.model.OWLOntologyLoaderConfiguration;
import org.semanticweb.owlapi.model.OWLOntologyManager;
import org.semanticweb.owlapi.reasoner.OWLReasoner;

public class O2uExplain {
    public static void main(String[] args) throws Exception {
        if (args.length != 3) {
            System.err.println("O2U-ERROR: usage: O2uExplain <ontology> <queries.txt> <out.txt>");
            System.exit(2);
        }
        OWLOntologyManager man = OWLManager.createOWLOntologyManager();
        OWLOntologyLoaderConfiguration conf = new OWLOntologyLoaderConfiguration()
                .setMissingImportHandlingStrategy(MissingImportHandlingStrategy.SILENT);
        man.setOntologyLoaderConfiguration(conf);
        OWLOntology ont = man.loadOntologyFromOntologyDocument(new File(args[0]));
        OWLDataFactory df = man.getOWLDataFactory();
        ReasonerFactory rf = new ReasonerFactory();
        List<String> lines = Files.readAllLines(new File(args[1]).toPath(), StandardCharsets.UTF_8);
        try (PrintWriter out = new PrintWriter(new File(args[2]), "UTF-8")) {
            ExplanationGenerator<OWLAxiom> gen = null;
            for (String line : lines) {
                if (line.trim().isEmpty()) continue;
                int tab = line.indexOf('\t');
                String id = tab < 0 ? line.trim() : line.substring(0, tab);
                Set<Explanation<OWLAxiom>> found;
                if (id.equals("!inconsistent")) {
                    ExplanationGenerator<OWLAxiom> ig =
                            new InconsistentOntologyExplanationGeneratorFactory(rf, Long.MAX_VALUE)
                                    .createExplanationGenerator(ont);
                    found = ig.getExplanations(
                            df.getOWLSubClassOfAxiom(df.getOWLThing(), df.getOWLNothing()), 1);
                } else {
                    OWLAxiom q = parse(line.substring(tab + 1));
                    if (q == null) {
                        out.println("@@ENTRY\t" + id + "\t-2");
                        out.println("@@END");
                        continue;
                    }
                    OWLReasoner r = rf.createReasoner(ont);
                    boolean entailed = r.isEntailed(q);
                    r.dispose();
                    if (!entailed) {
                        out.println("@@ENTRY\t" + id + "\t-1");
                        out.println("@@END");
                        continue;
                    }
                    if (gen == null) {
                        ExplanationGeneratorFactory<OWLAxiom> f =
                                ExplanationManager.createExplanationGeneratorFactory(rf);
                        gen = f.createExplanationGenerator(ont);
                    }
                    found = gen.getExplanations(q, 1);
                }
                if (found.isEmpty()) {
                    out.println("@@ENTRY\t" + id + "\t-1");
                    out.println("@@END");
                    continue;
                }
                Explanation<OWLAxiom> e = found.iterator().next();
                out.println("@@ENTRY\t" + id + "\t" + e.getAxioms().size());
                for (OWLAxiom ax : e.getAxioms()) {
                    out.println("@@AXIOM");
                    out.println(turtle(ax));
                }
                out.println("@@END");
                out.flush();
            }
        }
    }

    static OWLAxiom parse(String functional) {
        try {
            OWLOntologyManager m = OWLManager.createOWLOntologyManager();
            OWLOntology o = m.loadOntologyFromOntologyDocument(new StringDocumentSource(
                    "Ontology(<urn:o2u:query>\n" + functional + "\n)"));
            for (OWLAxiom ax : o.getLogicalAxioms()) {
                return ax;
            }
        } catch (Exception exc) {
            System.err.println("O2U-WARN: could not parse query: " + exc.getMessage());
        }
        return null;
    }

    static String turtle(OWLAxiom ax) throws Exception {
        OWLOntologyManager m = OWLManager.createOWLOntologyManager();
        OWLOntology o = m.createOntology(IRI.create("urn:o2u:justification"));
        m.addAxiom(o, ax);
        ByteArrayOutputStream buf = new ByteArrayOutputStream();
        m.saveOntology(o, new TurtleDocumentFormat(), buf);
        return buf.toString("UTF-8");
    }
}
