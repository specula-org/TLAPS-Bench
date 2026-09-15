import java.io.*;
import java.nio.file.*;
import java.util.*;
import tla2sany.drivers.SANY;
import tla2sany.modanalyzer.SpecObj;
import tla2sany.semantic.*;
import tla2sany.st.Location;
import util.UniqueString;

/**
 * SANY semantic dumper for tlaps-bench proof-from-scratch generator.
 *
 * Reads a single .tla file, parses it via SANY's frontEndMain,
 * and emits a JSON description of its module-level declarations
 * (constants, variables, assumes, instances, operator defs, theorems).
 *
 * Each declaration includes its source-line range so the Python
 * generator can splice/delete source text by range.
 *
 * Spec-formula identification (shape-based, not name-based) and the
 * BY/USE/DEFS reference graph for theorems are computed here too,
 * since both require walking the semantic AST.
 *
 * THEOREM vs LEMMA keyword distinction is NOT made here — both become
 * TheoremNode in SANY. The Python generator reads the source text at
 * the theorem's location to determine the keyword.
 */
public class DumpSemantics {

  // Built-in operator UniqueString names — see BuiltInOperators.class.
  static final String OP_IMPLIES = "=>";
  static final String OP_BOX = "[]";
  static final String OP_SQUARE_ACT = "$SquareAct"; // [A]_v
  static final String OP_ANGLE_ACT = "$AngleAct";   // <<A>>_v
  static final String OP_WF = "$WF";
  static final String OP_SF = "$SF";
  static final String OP_CONJ_LIST = "$ConjList";   // multi-conjunct /\ bullet list
  static final String OP_LAND = "\\land";           // binary /\

  public static void main(String[] args) throws Exception {
    if (args.length < 1) {
      System.err.println("Usage: java DumpSemantics <input.tla>");
      System.exit(2);
    }
    String fileName = args[0];

    SpecObj spec = new SpecObj(fileName);
    PrintStream sysOut = System.out;
    System.setOut(new PrintStream(new ByteArrayOutputStream()));
    try {
      SANY.frontEndMain(spec, fileName, new PrintStream(new ByteArrayOutputStream()));
    } finally {
      System.setOut(sysOut);
    }

    if (spec.getErrorLevel() > 0) {
      System.err.println("SANY parse error (errorLevel=" + spec.getErrorLevel() + ")");
      try { System.err.println(spec.parseErrors.toString()); } catch (Throwable t) {}
      try { System.err.println(spec.semanticErrors.toString()); } catch (Throwable t) {}
      System.exit(3);
    }

    ModuleNode root = spec.getRootModule();
    if (root == null) {
      System.err.println("No root module after parse");
      System.exit(4);
    }

    String json = dumpModule(root, fileName);
    // Sentinel marker so the Python reader can skip any SANY-internal output
    // that leaked to stdout (e.g. PlusCal "Labels added." or parse-error text).
    System.out.println("--- BEGIN SANY-DUMP JSON ---");
    System.out.println(json);
  }

  static String dumpModule(ModuleNode m, String mainFile) {
    String moduleFile = m.getTreeNode().getFilename();
    Set<String> specFormulas = findSpecFormulas(m, moduleFile);

    // Build the set of theorem names defined in THIS module (used for
    // resolving BY/USE references back to in-module theorems).
    Set<String> moduleTheoremNames = new LinkedHashSet<>();
    for (TheoremNode t : m.getTheorems()) {
      if (!isFromFile(t, moduleFile)) continue;
      UniqueString us = t.getName();
      if (us != null) moduleTheoremNames.add(us.toString());
    }

    // Build the set of names that the proof-from-scratch reachability pass can keep: in-module
    // operator definitions plus INSTANCE bindings. A reference to any of these
    // from the target theorem's statement (transitively) marks the definition
    // as "needed to state the goal", so it survives stripping; everything else
    // (inductive invariants, helper lemmas) is a proof artifact and is removed.
    Set<String> moduleDefNames = new LinkedHashSet<>();
    for (OpDefNode op : m.getOpDefs()) {
      if (!isFromFile(op, moduleFile)) continue;
      if (op.getSource() != op) continue;
      moduleDefNames.add(op.getName().toString());
    }
    for (InstanceNode inst : m.getInstances()) {
      if (!isFromFile(inst, moduleFile)) continue;
      UniqueString instName = inst.getName();
      if (instName != null) moduleDefNames.add(instName.toString());
    }

    JsonBuilder j = new JsonBuilder();
    j.openObject();
    j.field("module", m.getName().toString());
    j.field("source_file", mainFile);
    j.field("filename", new File(moduleFile).getName());

    // Module-level location (the whole file)
    int[] modLoc = locOf(m);
    if (modLoc != null) {
      j.field("module_line_start", modLoc[0]);
      j.field("module_line_end", modLoc[2]);
    }

    // EXTENDS
    j.openArrayField("extends");
    ModuleNode[] extendees = safeExtendees(m);
    if (extendees != null) {
      for (ModuleNode ext : extendees) j.stringElem(ext.getName().toString());
    }
    j.closeArray();

    // CONSTANTS
    j.openArrayField("constants");
    for (OpDeclNode c : m.getConstantDecls()) {
      if (!isFromFile(c, moduleFile)) continue;
      j.openObject();
      j.field("name", c.getName().toString());
      emitLoc(j, c);
      j.closeObject();
    }
    j.closeArray();

    // VARIABLES
    j.openArrayField("variables");
    for (OpDeclNode v : m.getVariableDecls()) {
      if (!isFromFile(v, moduleFile)) continue;
      j.openObject();
      j.field("name", v.getName().toString());
      emitLoc(j, v);
      j.closeObject();
    }
    j.closeArray();

    // ASSUME / AXIOM
    j.openArrayField("assumes");
    for (AssumeNode a : m.getAssumptions()) {
      if (!isFromFile(a, moduleFile)) continue;
      j.openObject();
      j.field("name", a.getDef() == null ? null : a.getDef().getName().toString());
      j.field("is_axiom", a.getIsAxiom());
      emitLoc(j, a);
      emitRefs(j, a, moduleDefNames);
      j.closeObject();
    }
    j.closeArray();

    // INSTANCE bindings (e.g. C == INSTANCE Consensus WITH ...)
    j.openArrayField("instances");
    for (InstanceNode inst : m.getInstances()) {
      if (!isFromFile(inst, moduleFile)) continue;
      j.openObject();
      UniqueString instName = inst.getName();
      j.field("name", instName == null ? null : instName.toString());
      ModuleNode target = inst.getModule();
      j.field("module", target == null ? null : target.getName().toString());
      emitLoc(j, inst);
      // References from the WITH substitution expressions: keeping a reachable
      // INSTANCE binding (e.g. for `Spec => C!Spec`) requires keeping every
      // local operator it substitutes in.
      emitRefs(j, inst, moduleDefNames);
      j.closeObject();
    }
    j.closeArray();

    // Nested modules
    j.openArrayField("inner_modules");
    for (ModuleNode inner : m.getInnerModules()) {
      if (!isFromFile(inner, moduleFile)) continue;
      j.openObject();
      j.field("name", inner.getName().toString());
      emitLoc(j, inner);
      j.closeObject();
    }
    j.closeArray();

    // Module-level USE/HIDE directives and any top-level node kind not covered
    // by the normalized schema above. Proof-step directives are nested inside
    // theorem proofs and therefore do not appear in m.getTopLevel().
    j.openArrayField("directives");
    for (LevelNode node : m.getTopLevel()) {
      if (!isFromFile(node, moduleFile) || !(node instanceof UseOrHideNode)) continue;
      UseOrHideNode directive = (UseOrHideNode) node;
      j.openObject();
      j.field("kind", node.getKind() == ASTConstants.UseKind ? "USE" : "HIDE");
      j.field("definitions_only",
              (directive.facts == null || directive.facts.length == 0)
              && directive.defs != null && directive.defs.length > 0);
      emitLoc(j, node);
      j.closeObject();
    }
    j.closeArray();

    j.openArrayField("other_top_levels");
    for (LevelNode node : m.getTopLevel()) {
      if (!isFromFile(node, moduleFile)
          || node instanceof TheoremNode
          || node instanceof AssumeNode
          || node instanceof InstanceNode
          || node instanceof UseOrHideNode) continue;
      j.openObject();
      j.field("kind", node.getClass().getSimpleName());
      emitLoc(j, node);
      j.closeObject();
    }
    j.closeArray();

    // Operator definitions
    j.openArrayField("operators");
    for (OpDefNode op : m.getOpDefs()) {
      if (!isFromFile(op, moduleFile)) continue;
      if (op.getSource() != op) continue; // skip INSTANCE-mediated copies of defs from other modules
      j.openObject();
      j.field("name", op.getName().toString());
      emitLoc(j, op);
      j.field("is_spec_formula", specFormulas.contains(op.getName().toString()));
      String bodyKind = classifyBody(op.getBody(), specFormulas);
      j.field("body_kind", bodyKind);
      // References from the body: the edges of the definition-dependency graph
      // the proof-from-scratch reachability pass walks. Includes params' default exprs etc. via
      // the generic child walk.
      Set<String> refs = new LinkedHashSet<>();
      collectOpRefs(op.getBody(), refs, moduleDefNames);
      emitRefArray(j, refs);
      j.closeObject();
    }
    j.closeArray();

    j.openArrayField("spec_formulas");
    for (String s : specFormulas) j.stringElem(s);
    j.closeArray();

    // Theorems / lemmas (SANY treats both as TheoremNode)
    j.openArrayField("theorems");
    for (TheoremNode t : m.getTheorems()) {
      if (!isFromFile(t, moduleFile)) continue;
      emitTheorem(j, t, specFormulas, moduleTheoremNames, moduleDefNames);
    }
    j.closeArray();

    j.closeObject();
    return j.finish();
  }

  // ----- theorem emission --------------------------------------------------

  static void emitTheorem(JsonBuilder j, TheoremNode t,
                          Set<String> specFormulas, Set<String> moduleTheoremNames,
                          Set<String> moduleDefNames) {
    j.openObject();
    UniqueString us = t.getName();
    j.field("name", us == null ? null : us.toString());
    emitLoc(j, t);
    LevelNode stmt = t.getTheorem();
    if (stmt != null) {
      j.openObjectField("statement_loc");
      int[] sl = locOf(stmt);
      writeLocFields(j, sl);
      j.closeObject();
    }
    ProofNode proof = t.getProof();
    if (proof != null) {
      j.openObjectField("proof_loc");
      int[] pl = locOf(proof);
      writeLocFields(j, pl);
      j.closeObject();
      LeafProofNode lp = (proof instanceof LeafProofNode) ? (LeafProofNode) proof : null;
      j.field("proof_is_omitted", lp != null && lp.getOmitted());
    } else {
      j.fieldNull("proof_loc");
      j.field("proof_is_omitted", false);
    }
    // Shape
    j.openObjectField("shape");
    classifyTheoremShape(j, stmt, specFormulas);
    j.closeObject();
    // References (theorem names referenced via BY/USE/DEFS in the proof)
    Set<String> refs = new LinkedHashSet<>();
    if (proof != null) collectRefs(proof, refs, moduleTheoremNames);
    j.openArrayField("references");
    for (String r : refs) j.stringElem(r);
    j.closeArray();
    // statement_references: the operator/INSTANCE definitions the *statement*
    // depends on. These seed the proof-from-scratch reachability pass — only definitions
    // reachable from here (transitively) are needed to state the goal.
    Set<String> stmtRefs = new LinkedHashSet<>();
    collectOpRefs(stmt, stmtRefs, moduleDefNames);
    j.openArrayField("statement_references");
    for (String r : stmtRefs) j.stringElem(r);
    j.closeArray();
    j.closeObject();
  }

  static void classifyTheoremShape(JsonBuilder j, LevelNode stmt, Set<String> specFormulas) {
    if (stmt instanceof OpApplNode) {
      OpApplNode app = (OpApplNode) stmt;
      String opName = symbolName(app.getOperator());
      if (OP_IMPLIES.equals(opName) && app.getArgs().length == 2) {
        j.field("kind", "implies");
        String lhs = bareRefName(app.getArgs()[0]);
        j.field("lhs_spec_ref",
                lhs != null && specFormulas.contains(lhs) ? lhs : null);
        int[] rhsLoc = locOf(app.getArgs()[1]);
        if (rhsLoc != null) {
          j.openObjectField("rhs_loc");
          writeLocFields(j, rhsLoc);
          j.closeObject();
        } else {
          j.fieldNull("rhs_loc");
        }
        j.field("rhs_primary_name", primaryName(app.getArgs()[1]));
        return;
      }
    } else if (stmt instanceof AssumeProveNode) {
      j.field("kind", "assume_prove");
      j.field("lhs_spec_ref", null);
      j.fieldNull("rhs_loc");
      j.field("rhs_primary_name", null);
      return;
    }
    j.field("kind", "other");
    j.field("lhs_spec_ref", null);
    j.fieldNull("rhs_loc");
    j.field("rhs_primary_name", null);
  }

  // For unnamed THEOREM Spec => []TerminationDetection, this returns
  // "TerminationDetection" (peels off temporal modalities + simple wrappers).
  static String primaryName(ExprOrOpArgNode node) {
    if (!(node instanceof OpApplNode)) return null;
    OpApplNode app = (OpApplNode) node;
    String opName = symbolName(app.getOperator());
    // Peel temporal modalities and a few simple wrappers.
    if (OP_BOX.equals(opName) || "<>".equals(opName) || "~>".equals(opName)) {
      if (app.getArgs().length >= 1) return primaryName(app.getArgs()[0]);
    }
    if (OP_SQUARE_ACT.equals(opName) || OP_ANGLE_ACT.equals(opName)) {
      if (app.getArgs().length >= 1) return primaryName(app.getArgs()[0]);
    }
    // Bare reference (zero args) → use operator's name.
    if (app.getArgs().length == 0) return opName;
    // Otherwise return null (no obvious primary name).
    return null;
  }

  static String bareRefName(ExprOrOpArgNode node) {
    if (!(node instanceof OpApplNode)) return null;
    OpApplNode app = (OpApplNode) node;
    if (app.getArgs().length != 0) return null;
    return symbolName(app.getOperator());
  }

  // ----- definition-dependency graph (for proof-from-scratch reachability) -----------------

  /**
   * Walk an arbitrary semantic subtree and collect the names of in-module
   * operator / INSTANCE definitions it applies. This builds the edges of the
   * definition-dependency graph the proof-from-scratch generator uses to decide which `==`
   * definitions are needed to state the goal (kept) versus pure proof
   * artifacts (stripped).
   *
   * We record the name at each OpApplNode or OpArgNode whose operator resolves
   * to an in-module definition, then recurse over getChildren() so nested
   * applications, LET/IN bodies, quantifier bodies, records, etc. are all
   * covered. OpArgNode represents a named operator passed as an argument and
   * has no children, so it must be handled directly. Bound variables and
   * parameters are not in moduleDefNames, so they are naturally ignored.
   */
  static void collectOpRefs(SemanticNode n, Set<String> out, Set<String> moduleDefNames) {
    if (n == null) return;
    if (n instanceof OpApplNode) {
      collectOpRef(((OpApplNode) n).getOperator(), out, moduleDefNames);
    } else if (n instanceof OpArgNode) {
      collectOpRef(((OpArgNode) n).getOp(), out, moduleDefNames);
    }
    SemanticNode[] kids;
    try {
      kids = n.getChildren();
    } catch (Throwable t) {
      kids = null;
    }
    if (kids != null) {
      for (SemanticNode k : kids) collectOpRefs(k, out, moduleDefNames);
    }
  }

  static void collectOpRef(SymbolNode op, Set<String> out, Set<String> moduleDefNames) {
    String nm = symbolName(op);
    if (nm == null) return;
    if (moduleDefNames.contains(nm)) out.add(nm);
    // INSTANCE-qualified use (e.g. `C!Spec`): SANY names the operator with
    // the `!` separator. Map it back to the local INSTANCE binding `C` so that
    // keeping a refinement target like `Spec => C!Spec` also keeps the instance
    // (and, transitively, its WITH substitution operators).
    int bang = nm.indexOf('!');
    if (bang > 0) {
      String prefix = nm.substring(0, bang);
      if (moduleDefNames.contains(prefix)) out.add(prefix);
    }
  }

  static void emitRefs(JsonBuilder j, SemanticNode n, Set<String> moduleDefNames) {
    Set<String> refs = new LinkedHashSet<>();
    collectOpRefs(n, refs, moduleDefNames);
    emitRefArray(j, refs);
  }

  static void emitRefArray(JsonBuilder j, Set<String> refs) {
    j.openArrayField("references");
    for (String r : refs) j.stringElem(r);
    j.closeArray();
  }

  // ----- theorem-use graph (BY/USE/DEFS, for top-level selection) ----------

  static void collectRefs(ProofNode p, Set<String> refs, Set<String> moduleTheoremNames) {
    Set<Integer> visited = new HashSet<Integer>();
    if (p instanceof LeafProofNode) {
      LeafProofNode lp = (LeafProofNode) p;
      for (LevelNode f : lp.getFacts()) {
        collectTheoremRefsFromFact(f, refs, moduleTheoremNames, visited);
      }
      for (SymbolNode d : lp.getDefs()) {
        collectTheoremRefsFromSymbol(d, refs, moduleTheoremNames, visited);
      }
    } else if (p instanceof NonLeafProofNode) {
      for (LevelNode step : ((NonLeafProofNode) p).getSteps()) {
        if (step instanceof TheoremNode) {
          ProofNode sub = ((TheoremNode) step).getProof();
          if (sub != null) collectRefs(sub, refs, moduleTheoremNames);
        } else if (step instanceof UseOrHideNode) {
          UseOrHideNode u = (UseOrHideNode) step;
          // HIDE removes facts/definitions from the usable context.  It must
          // not create a proof dependency merely because it names an earlier
          // theorem.  USE is the directive that makes those facts available.
          if (u.getKind() != ASTConstants.UseKind) continue;
          if (u.facts != null) {
            for (LevelNode f : u.facts) {
              collectTheoremRefsFromFact(f, refs, moduleTheoremNames, visited);
            }
          }
          if (u.defs != null) {
            for (SymbolNode d : u.defs) {
              collectTheoremRefsFromSymbol(d, refs, moduleTheoremNames, visited);
            }
          }
        } else if (step instanceof DefStepNode) {
          // References inside proof-local DEFINE bodies are collected by the
          // semantic walk below. They matter for dependency-closed scoring:
          // `DEFINE Alias == EarlierTheorem` must not hide that dependency.
        }
        // InstanceNode steps and others: no refs.
      }
    }
  }

  static void collectTheoremRefs(
      SemanticNode node,
      Set<String> refs,
      Set<String> moduleTheoremNames,
      Set<Integer> visited) {
    if (node == null || !visited.add(node.getUid())) return;
    if (node instanceof OpApplNode) {
      collectTheoremRefsFromSymbol(
          ((OpApplNode) node).getOperator(), refs, moduleTheoremNames, visited);
    }
    SemanticNode[] children;
    try {
      children = node.getChildren();
    } catch (Throwable t) {
      children = null;
    }
    if (children != null) {
      for (SemanticNode child : children) {
        collectTheoremRefs(child, refs, moduleTheoremNames, visited);
      }
    }
  }

  static void collectTheoremRefsFromSymbol(
      SymbolNode symbol,
      Set<String> refs,
      Set<String> moduleTheoremNames,
      Set<Integer> visited) {
    addRefFromSymbol(symbol, refs, moduleTheoremNames);
    if (symbol instanceof OpDefNode) {
      // An admitted theorem can otherwise be hidden behind a proof-local or
      // helper-region operator and cited only through `BY ... DEF Alias`.
      collectTheoremRefs(((OpDefNode) symbol).getBody(), refs, moduleTheoremNames, visited);
    }
  }

  static void collectTheoremRefsFromFact(
      LevelNode fact,
      Set<String> refs,
      Set<String> moduleTheoremNames,
      Set<Integer> visited) {
    // A BY/USE fact can hide a theorem arbitrarily deeply through user
    // operators, LET/IN, CASE, or other semantic wrappers. Conservatively walk
    // the complete fact subtree. This can retain a dependency when a theorem
    // name occurs in a tautological composite fact, but it cannot award trust
    // to a proof whose usable fact was derived from an admitted theorem.
    collectTheoremRefs(fact, refs, moduleTheoremNames, visited);
  }

  static void addRefFromSymbol(SymbolNode sym, Set<String> refs, Set<String> moduleTheoremNames) {
    if (sym == null) return;
    String name = symbolName(sym);
    if (name != null && moduleTheoremNames.contains(name)) refs.add(name);
  }

  // ----- spec formula identification --------------------------------------

  static Set<String> findSpecFormulas(ModuleNode m, String moduleFile) {
    Set<String> known = new LinkedHashSet<>();
    boolean changed = true;
    int pass = 0;
    while (changed && pass < 8) {
      changed = false;
      pass++;
      for (OpDefNode op : m.getOpDefs()) {
        if (!isFromFile(op, moduleFile)) continue;
        if (op.getSource() != op) continue;
        String name = op.getName().toString();
        if (known.contains(name)) continue;
        if (classifyBody(op.getBody(), known) != null) {
          known.add(name);
          changed = true;
        }
      }
    }
    return known;
  }

  /**
   * Classify an OpDefNode body. Returns null if the body is NOT a temporal
   * closure of a transition system; otherwise returns a short tag:
   *  - "temporal_closure":  conjunction containing [][A]_v
   *  - "fairness_closure":  KnownSpec /\ WF/SF...
   *
   * A bare `[][A]_v` (not inside a conjunction) is intentionally NOT a spec
   * formula — that pattern is used for action properties / non-invariants
   * (e.g. EWD840's NeverChangeColor), not for behavioral specs.
   */
  static String classifyBody(ExprNode body, Set<String> knownSpecs) {
    if (body == null) return null;
    if (!(body instanceof OpApplNode)) return null;
    OpApplNode app = (OpApplNode) body;
    if (!isConjLike(symbolName(app.getOperator()))) return null;

    List<ExprOrOpArgNode> conjs = new ArrayList<>();
    flattenConjuncts(app, conjs);

    boolean hasSquareBox = false;
    boolean hasKnownSpec = false;
    boolean hasFairness = false;
    for (ExprOrOpArgNode arg : conjs) {
      if (isSquareActionBox(arg)) { hasSquareBox = true; continue; }
      if (isFairness(arg)) { hasFairness = true; continue; }
      String ref = bareRefName(arg);
      if (ref != null && knownSpecs.contains(ref)) { hasKnownSpec = true; continue; }
    }
    if (hasSquareBox) return "temporal_closure";
    if (hasKnownSpec && hasFairness) return "fairness_closure";
    return null;
  }

  static void flattenConjuncts(ExprOrOpArgNode node, List<ExprOrOpArgNode> out) {
    if (node instanceof OpApplNode) {
      OpApplNode app = (OpApplNode) node;
      if (isConjLike(symbolName(app.getOperator()))) {
        for (ExprOrOpArgNode arg : app.getArgs()) flattenConjuncts(arg, out);
        return;
      }
    }
    out.add(node);
  }

  static boolean isConjLike(String opName) {
    return OP_CONJ_LIST.equals(opName) || OP_LAND.equals(opName);
  }

  static boolean isSquareActionBox(ExprOrOpArgNode node) {
    // Match `[][A]_v`: OpApplNode whose op is `[]` and whose arg is `$SquareAct`-applied.
    if (!(node instanceof OpApplNode)) return false;
    OpApplNode app = (OpApplNode) node;
    if (!OP_BOX.equals(symbolName(app.getOperator()))) return false;
    if (app.getArgs().length != 1) return false;
    ExprOrOpArgNode inner = app.getArgs()[0];
    if (!(inner instanceof OpApplNode)) return false;
    String innerOp = symbolName(((OpApplNode) inner).getOperator());
    return OP_SQUARE_ACT.equals(innerOp);
  }

  static boolean isFairness(ExprOrOpArgNode node) {
    if (!(node instanceof OpApplNode)) return false;
    String op = symbolName(((OpApplNode) node).getOperator());
    return OP_WF.equals(op) || OP_SF.equals(op);
  }

  // ----- helpers -----------------------------------------------------------

  static String symbolName(SymbolNode op) {
    if (op == null) return null;
    UniqueString us = op.getName();
    return us == null ? null : us.toString();
  }

  static int[] locOf(SemanticNode n) {
    if (n == null || n.getTreeNode() == null) return null;
    Location loc = n.getTreeNode().getLocation();
    if (loc == null) return null;
    return new int[]{ loc.beginLine(), loc.beginColumn(), loc.endLine(), loc.endColumn() };
  }

  static void emitLoc(JsonBuilder j, SemanticNode n) {
    int[] l = locOf(n);
    j.openObjectField("loc");
    writeLocFields(j, l);
    j.closeObject();
  }

  static void writeLocFields(JsonBuilder j, int[] l) {
    if (l == null) {
      j.field("line_start", -1);
      j.field("column_start", -1);
      j.field("line_end", -1);
      j.field("column_end", -1);
      return;
    }
    j.field("line_start", l[0]);
    j.field("column_start", l[1]);
    j.field("line_end", l[2]);
    j.field("column_end", l[3]);
  }

  static boolean isFromFile(SemanticNode n, String moduleFile) {
    if (n == null || n.getTreeNode() == null) return false;
    String f = n.getTreeNode().getFilename();
    return f != null && f.equals(moduleFile);
  }

  static ModuleNode[] safeExtendees(ModuleNode m) {
    try {
      java.lang.reflect.Field f = ModuleNode.class.getDeclaredField("extendees");
      f.setAccessible(true);
      Object v = f.get(m);
      if (v instanceof ModuleNode[]) return (ModuleNode[]) v;
    } catch (Throwable t) { /* ignore */ }
    return new ModuleNode[0];
  }

  // ----- tiny handcrafted JSON writer -------------------------------------

  static class JsonBuilder {
    private final StringBuilder sb = new StringBuilder();
    // Stack tracks whether each open container has emitted at least one element.
    private final Deque<Boolean> needsComma = new ArrayDeque<>();
    private boolean inContainer() { return !needsComma.isEmpty(); }
    private void preElement() {
      if (inContainer()) {
        if (needsComma.peek()) sb.append(',');
        needsComma.pop();
        needsComma.push(true);
      }
    }
    void openObject() { preElement(); sb.append('{'); needsComma.push(false); }
    void closeObject() { sb.append('}'); needsComma.pop(); }
    void openArrayField(String name) { preElement(); writeName(name); sb.append('['); needsComma.push(false); }
    void openObjectField(String name) { preElement(); writeName(name); sb.append('{'); needsComma.push(false); }
    void closeArray() { sb.append(']'); needsComma.pop(); }
    void field(String name, String v) { preElement(); writeName(name); writeStringOrNull(v); }
    void field(String name, int v) { preElement(); writeName(name); sb.append(v); }
    void field(String name, boolean v) { preElement(); writeName(name); sb.append(v ? "true" : "false"); }
    void fieldNull(String name) { preElement(); writeName(name); sb.append("null"); }
    void stringElem(String v) { preElement(); writeStringOrNull(v); }
    String finish() { return sb.toString(); }
    private void writeName(String name) { writeString(name); sb.append(':'); }
    private void writeStringOrNull(String v) {
      if (v == null) sb.append("null"); else writeString(v);
    }
    private void writeString(String s) {
      sb.append('"');
      for (int i = 0; i < s.length(); i++) {
        char c = s.charAt(i);
        switch (c) {
          case '"': sb.append("\\\""); break;
          case '\\': sb.append("\\\\"); break;
          case '\b': sb.append("\\b"); break;
          case '\f': sb.append("\\f"); break;
          case '\n': sb.append("\\n"); break;
          case '\r': sb.append("\\r"); break;
          case '\t': sb.append("\\t"); break;
          default:
            if (c < 0x20) sb.append(String.format("\\u%04x", (int) c));
            else sb.append(c);
        }
      }
      sb.append('"');
    }
  }
}
