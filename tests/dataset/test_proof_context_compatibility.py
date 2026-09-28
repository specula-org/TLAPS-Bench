"""Exercise recursive bindings, function applications, and parameter domains."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tlacore.tlapm.locate import find_tlapm

REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / "source"
ELEVATOR = SOURCE / "tlaplus_examples_MultiCarElevator"
LIBS = [REPO / "lib/tlapm", REPO / "lib/community"]


def _tlapm(tmp_path, text, include=()):
    binary = find_tlapm()
    if binary is None or not all(path.is_dir() for path in LIBS):
        pytest.skip("TLAPM and pinned proof libraries are required")
    probe = tmp_path / "Probe.tla"
    probe.write_text(text)
    command = [binary, "--strict", "--nofp", "--threads", "1"]
    for path in (*include, *LIBS):
        command += ["-I", str(path)]
    result = subprocess.run(command + [str(probe)], cwd=tmp_path, capture_output=True, text=True, timeout=180)
    output = result.stdout + result.stderr
    (tmp_path / "tlapm.log").write_text(output)
    assert result.returncode == 0, output
    assert "All" in output and "obligations proved" in output, output


def _tlc(tmp_path, text, config, include=(), success=True):
    jar = REPO / "lib/tla2tools.jar"
    if shutil.which("java") is None or not jar.is_file():
        pytest.skip("TLC and pinned tla2tools.jar are required")
    (tmp_path / "Probe.tla").write_text(text)
    (tmp_path / "Probe.cfg").write_text(config)
    classpath = os.pathsep.join(map(str, (jar, tmp_path, *include, *LIBS)))
    result = subprocess.run(
        ["java", "-Xmx512m", "-cp", classpath, "tlc2.TLC", "-workers", "1", "-config", "Probe.cfg", "Probe"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=180,
    )
    output = result.stdout + result.stderr
    output_dir = tmp_path / "spec/output"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "tlc.log").write_text(output)
    if success:
        assert result.returncode == 0, output
        assert "Model checking completed. No error has been found." in output, output
    else:
        assert result.returncode != 0, output
    return output


def _cycle_helper():
    text = (SOURCE / "CahillSSI/CahillSSIModel.tla").read_text()
    return text[text.index("FindAllNodesInAnyCycle(edges) ==") : text.index("IsCycle(edges) ==")]


def test_cahill_rendering_matches_pinned_source():
    result = subprocess.run(
        [sys.executable, str(SOURCE / "CahillSSI/prepare.py"), "--check"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_cahill_recursive_function_application(tmp_path):
    # Check the actual recursive step as a function of an arbitrary previous
    # function. This isolates application encoding from well-foundedness.
    helper = _cycle_helper()
    start = helper.index("findCycleNodes[node")
    end = helper.index("startPoints", start)
    step = helper[start:end].strip().replace("findCycleNodes[neighbor]", "previous[neighbor]")
    _tlapm(
        tmp_path,
        r"""---- MODULE Probe ----
EXTENDS Naturals, Sequences, FiniteSets, TLAPS
Step(nodes, edges, previous) ==
  LET """
        + step
        + r"""
  IN findCycleNodes
THEOREM VisitedNode ==
  ASSUME NEW nodes, NEW edges, NEW previous,
         NEW n \in nodes, NEW visited \in SUBSET nodes, n \in visited
  PROVE Step(nodes, edges, previous)[n][visited] = {n}
BY Zenon DEF Step
====
""",
    )


def test_cahill_cycle_nodes_agree_with_bounded_paths(tmp_path):
    output = _tlc(
        tmp_path,
        r"""---- MODULE Probe ----
EXTENDS Naturals, Sequences, FiniteSets
"""
        + _cycle_helper()
        + r"""
VARIABLE edges
Nodes == 1..3
Init == edges \in SUBSET (Nodes \X Nodes)
Next == UNCHANGED edges
Expected == {n \in Nodes :
  \E length \in 1..3 : \E path \in [0..length -> Nodes] :
    /\ path[0] = n
    /\ path[length] = n
    /\ \A i \in 1..length : <<path[i-1], path[i]>> \in edges}
Correct == FindAllNodesInAnyCycle(edges) = Expected
====
""",
        "INIT Init\nNEXT Next\nINVARIANT Correct\nCHECK_DEADLOCK FALSE\n",
    )
    assert "512 distinct states found" in output, output


@pytest.mark.parametrize("module", ["MongoDB/Util.tla", "tlaplus_examples_allocator/SchedulingAllocator.tla"])
def test_instantiated_permutations_unfold_and_preserve_values(tmp_path, module):
    text = (SOURCE / module).read_text()
    start = text.index("PermSeqs(S) ==")
    end = text.index("IN  perms[S]", start) + len("IN  perms[S]")
    (tmp_path / "Permutations.tla").write_text(
        "---- MODULE Permutations ----\nEXTENDS Naturals, Sequences, FiniteSets\n" + text[start:end] + "\n====\n"
    )
    _tlapm(
        tmp_path,
        r"""---- MODULE Probe ----
EXTENDS Naturals, Sequences, FiniteSets, TLAPS
P == INSTANCE Permutations
Body(g, ss) == IF ss = {} THEN {<<>>}
              ELSE UNION {{Append(sq, x) : sq \in g[ss \ {x}]} : x \in ss}
Fn(S) == CHOOSE g : g = [ss \in SUBSET S |-> Body(g, ss)]
THEOREM InstantiatedRecursion ==
  ASSUME NEW S
  PROVE P!PermSeqs(S) = Fn(S)[S]
BY Zenon DEF P!PermSeqs, Fn, Body
====
""",
    )
    output = _tlc(
        tmp_path,
        r"""---- MODULE Probe ----
EXTENDS Naturals, Sequences, FiniteSets
P == INSTANCE Permutations
VARIABLE S
Init == S \in SUBSET (1..4)
Next == UNCHANGED S
Expected == {s \in [1..Cardinality(S) -> S] : {s[i] : i \in DOMAIN s} = S}
Correct == P!PermSeqs(S) = Expected
====
""",
        "INIT Init\nNEXT Next\nINVARIANT Correct\nCHECK_DEADLOCK FALSE\n",
    )
    assert "16 distinct states found" in output, output


def test_elevator_function_applications(tmp_path):
    _tlapm(
        tmp_path,
        r"""---- MODULE Probe ----
EXTENDS Elevator, TLAPS
THEOREM Distance ==
  ASSUME NEW a \in Floor, NEW b \in Floor
  PROVE GetDistance[<<a, b>>] = IF a > b THEN a - b ELSE b - a
BY Zenon DEF GetDistance
THEOREM DirectionEval ==
  ASSUME NEW a \in Floor, NEW b \in Floor
  PROVE GetDirection[<<a, b>>] = IF b > a THEN "Up" ELSE "Down"
BY Zenon DEF GetDirection
THEOREM Service ==
  ASSUME NEW e \in Elevator, NEW c \in ElevatorCall
  PROVE CanServiceCall[<<e, c>>] <=>
    (c.floor = ElevatorState[e].floor /\ c.direction = ElevatorState[e].direction)
BY Zenon DEF CanServiceCall
THEOREM Waiting ==
  ASSUME NEW f \in Floor, NEW d \in Direction
  PROVE PeopleWaiting[<<f, d>>] =
    {p \in Person : /\ PersonState[p].location = f
                    /\ PersonState[p].waiting
                    /\ GetDirection[<<PersonState[p].location, PersonState[p].destination>>] = d}
BY Zenon DEF PeopleWaiting
====
""",
        [ELEVATOR],
    )


def test_elevator_integer_interval_has_no_gaps(tmp_path):
    _tlapm(
        tmp_path,
        r"""---- MODULE Probe ----
EXTENDS Elevator, TLAPS
THEOREM NextFloorUp ==
  ASSUME NEW current \in Floor, NEW destination \in Floor, current < destination
  PROVE /\ current + 1 \in Floor
        /\ current + 1 <= destination
BY FloorCountIsInteger, SMT DEF Floor
THEOREM NextFloorDown ==
  ASSUME NEW current \in Floor, NEW destination \in Floor, current > destination
  PROVE /\ current - 1 \in Floor
        /\ current - 1 >= destination
BY FloorCountIsInteger, SMT DEF Floor
====
""",
        [ELEVATOR],
    )


def test_elevator_reachable_states_and_function_values(tmp_path):
    output = _tlc(
        tmp_path,
        r"""---- MODULE Probe ----
EXTENDS Elevator
ASSUME Floor \cap Elevator = {}
DistanceOld[a \in Floor, b \in Floor] == IF a > b THEN a-b ELSE b-a
DirectionOld[a \in Floor, b \in Floor] == IF b > a THEN "Up" ELSE "Down"
ServiceOld[e \in Elevator, c \in ElevatorCall] ==
  c.floor = ElevatorState[e].floor /\ c.direction = ElevatorState[e].direction
WaitingOld[f \in Floor, d \in Direction] ==
  {p \in Person : /\ PersonState[p].location = f
                  /\ PersonState[p].waiting
                  /\ DirectionOld[PersonState[p].location, PersonState[p].destination] = d}
ValuesPreserved ==
  /\ GetDistance = DistanceOld
  /\ GetDirection = DirectionOld
  /\ CanServiceCall = ServiceOld
  /\ PeopleWaiting = WaitingOld
====
""",
        """CONSTANTS Person = {p} Elevator = {e} FloorCount = 3
INIT Init
NEXT Next
INVARIANTS TypeInvariant SafetyInvariant ValuesPreserved
CHECK_DEADLOCK FALSE
""",
        [ELEVATOR],
    )
    assert "123 distinct states found" in output, output


@pytest.mark.parametrize("bound", ["-1", "0", "1", "1000000", "TRUE"])
def test_elevator_floor_count_domain(tmp_path, bound):
    output = _tlc(
        tmp_path,
        r"""---- MODULE Probe ----
EXTENDS Elevator
Bound == BOUND_VALUE
InitProbe == /\ PersonState = <<>> /\ ElevatorState = <<>> /\ ActiveElevatorCalls = {}
NextProbe == UNCHANGED Vars
====
""".replace("BOUND_VALUE", bound),
        """CONSTANTS Person = {} Elevator = {} FloorCount <- Bound
INIT InitProbe
NEXT NextProbe
CHECK_DEADLOCK FALSE
""",
        [ELEVATOR],
        success=bound != "TRUE",
    )
    if bound == "TRUE":
        assert "Evaluating assumption" in output and "is an element of Int" in output, output
