// Batched satisfiability and entailment checks for `owl2uml claims`.
//
// Usage: java -cp <reasoner classpath>[:dir] O2uProbe <factory-class> <ontology> <queries.txt> <out.txt>
//   factory-class: an OWLReasonerFactory, e.g. org.semanticweb.HermiT.ReasonerFactory
//                  (robot.jar, OWL API 4) or
//                  com.clarkparsia.pellet.owlapiv3.PelletReasonerFactory
//                  (Pellet 2.3 as bundled with owlready2, OWL API 3).
//   This file uses only calls that OWL API 3.4 and 4.5 share, so the same
//   source compiles against either classpath.
//   ontology:      RDF/XML, without owl:imports (owl2uml passes the merged closure)
//   queries.txt:   tab-separated lines
//     C <i> <iri>          declare class i         P <i> <iri>   object property i
//     I <i> <iri>          declare individual i
//     SUPERS <id> <expr>   every named superclass (and equivalent) of expr
//     SAT <id> <expr>      is expr satisfiable?
//     SUB <id> <x> <y>     is x SubClassOf y entailed?
//   Expressions are prefix terms: cN, T (Thing), F (Nothing), (and x y ...),
//   (or x y ...), (not x), (some p x), (only p x), (value p iN),
//   (min n p x), (max n p x), (exactly n p x), where p is pN or (inv pN).
//
// Output: "CONSISTENT\t1|0" first, then one line per query:
//   "<id>\t1" or "<id>\t0" (SAT, SUB), "<id>\t<iri>\t<iri>..." (SUPERS),
//   "<id>\tERR\t<message>" when a query cannot be answered.
import java.io.File;
import java.io.PrintWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;

import org.semanticweb.owlapi.apibinding.OWLManager;
import org.semanticweb.owlapi.model.IRI;
import org.semanticweb.owlapi.model.OWLClass;
import org.semanticweb.owlapi.model.OWLClassExpression;
import org.semanticweb.owlapi.model.OWLDataFactory;
import org.semanticweb.owlapi.model.OWLObjectPropertyExpression;
import org.semanticweb.owlapi.model.OWLOntology;
import org.semanticweb.owlapi.model.OWLOntologyManager;
import org.semanticweb.owlapi.reasoner.OWLReasoner;
import org.semanticweb.owlapi.reasoner.OWLReasonerFactory;

public class O2uProbe {
    static OWLDataFactory df;
    static Map<String, String> classes = new HashMap<String, String>();
    static Map<String, String> props = new HashMap<String, String>();
    static Map<String, String> inds = new HashMap<String, String>();

    public static void main(String[] args) throws Exception {
        if (args.length != 4) {
            System.err.println("O2U-ERROR: usage: O2uProbe <factory> <ontology> <queries> <out>");
            System.exit(2);
        }
        OWLReasonerFactory rf = (OWLReasonerFactory) Class.forName(args[0]).newInstance();
        OWLOntologyManager man = OWLManager.createOWLOntologyManager();
        OWLOntology ont = man.loadOntologyFromOntologyDocument(new File(args[1]));
        df = man.getOWLDataFactory();
        OWLReasoner r = rf.createReasoner(ont);
        List<String> lines = Files.readAllLines(new File(args[2]).toPath(), StandardCharsets.UTF_8);
        PrintWriter out = new PrintWriter(new File(args[3]), "UTF-8");
        boolean consistent = r.isConsistent();
        out.println("CONSISTENT\t" + (consistent ? "1" : "0"));
        if (!consistent) {
            out.close();
            return;
        }
        for (String line : lines) {
            if (line.trim().isEmpty()) continue;
            String[] f = line.split("\t");
            String kind = f[0];
            try {
                if (kind.equals("C")) { classes.put(f[1], f[2]); continue; }
                if (kind.equals("P")) { props.put(f[1], f[2]); continue; }
                if (kind.equals("I")) { inds.put(f[1], f[2]); continue; }
                String id = f[1];
                if (kind.equals("SAT")) {
                    out.println(id + "\t" + (r.isSatisfiable(expr(f[2])) ? "1" : "0"));
                } else if (kind.equals("SUB")) {
                    OWLClassExpression x = expr(f[2]), y = expr(f[3]);
                    out.println(id + "\t" + (r.isEntailed(df.getOWLSubClassOfAxiom(x, y)) ? "1" : "0"));
                } else if (kind.equals("SUPERS")) {
                    OWLClassExpression x = expr(f[2]);
                    Set<String> found = new TreeSet<String>();
                    for (OWLClass c : r.getSuperClasses(x, false).getFlattened()) {
                        found.add(c.getIRI().toString());
                    }
                    for (OWLClass c : r.getEquivalentClasses(x).getEntities()) {
                        found.add(c.getIRI().toString());
                    }
                    StringBuilder sb = new StringBuilder(id);
                    for (String s : found) sb.append('\t').append(s);
                    out.println(sb);
                } else {
                    out.println("?\tERR\tunknown query kind " + kind);
                }
            } catch (Exception exc) {
                out.println((f.length > 1 ? f[1] : "?") + "\tERR\t" + String.valueOf(exc).replace('\t', ' ').replace('\n', ' '));
            }
        }
        out.close();
        r.dispose();
    }

    // ---- prefix-term parser -------------------------------------------------
    static int pos;
    static String src;

    static OWLClassExpression expr(String s) {
        src = s;
        pos = 0;
        return parseExpr();
    }

    static void skip() {
        while (pos < src.length() && src.charAt(pos) == ' ') pos++;
    }

    static String token() {
        skip();
        int start = pos;
        while (pos < src.length() && " ()".indexOf(src.charAt(pos)) < 0) pos++;
        return src.substring(start, pos);
    }

    static OWLClassExpression parseExpr() {
        skip();
        if (src.charAt(pos) != '(') {
            String t = token();
            if (t.equals("T")) return df.getOWLThing();
            if (t.equals("F")) return df.getOWLNothing();
            return df.getOWLClass(IRI.create(need(classes, t)));
        }
        pos++;
        String op = token();
        OWLClassExpression result;
        if (op.equals("and") || op.equals("or")) {
            Set<OWLClassExpression> parts = new HashSet<OWLClassExpression>();
            while (true) {
                skip();
                if (src.charAt(pos) == ')') break;
                parts.add(parseExpr());
            }
            result = op.equals("and") ? df.getOWLObjectIntersectionOf(parts)
                                      : df.getOWLObjectUnionOf(parts);
        } else if (op.equals("not")) {
            result = df.getOWLObjectComplementOf(parseExpr());
        } else if (op.equals("some") || op.equals("only")) {
            OWLObjectPropertyExpression p = parseProp();
            OWLClassExpression x = parseExpr();
            result = op.equals("some") ? df.getOWLObjectSomeValuesFrom(p, x)
                                       : df.getOWLObjectAllValuesFrom(p, x);
        } else if (op.equals("value")) {
            OWLObjectPropertyExpression p = parseProp();
            String i = token();
            result = df.getOWLObjectHasValue(p, df.getOWLNamedIndividual(IRI.create(need(inds, i))));
        } else if (op.equals("min") || op.equals("max") || op.equals("exactly")) {
            int n = Integer.parseInt(token());
            OWLObjectPropertyExpression p = parseProp();
            OWLClassExpression x = parseExpr();
            result = op.equals("min") ? df.getOWLObjectMinCardinality(n, p, x)
                    : op.equals("max") ? df.getOWLObjectMaxCardinality(n, p, x)
                    : df.getOWLObjectExactCardinality(n, p, x);
        } else {
            throw new IllegalArgumentException("unknown operator " + op);
        }
        skip();
        pos++;  // ')'
        return result;
    }

    static OWLObjectPropertyExpression parseProp() {
        skip();
        if (src.charAt(pos) == '(') {
            pos++;
            String op = token();
            if (!op.equals("inv")) throw new IllegalArgumentException("expected inv, got " + op);
            String t = token();
            skip();
            pos++;
            return df.getOWLObjectInverseOf(df.getOWLObjectProperty(IRI.create(need(props, t))));
        }
        return df.getOWLObjectProperty(IRI.create(need(props, token())));
    }

    static String need(Map<String, String> table, String key) {
        String k = key.substring(1);
        String v = table.get(k);
        if (v == null) throw new IllegalArgumentException("undeclared " + key);
        return v;
    }
}
