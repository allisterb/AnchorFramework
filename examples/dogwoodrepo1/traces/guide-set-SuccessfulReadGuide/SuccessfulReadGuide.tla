---------------------------- MODULE SuccessfulReadGuide ----------------------------
\* THE CONTROL. SuccessfulRead.tla, claims and sessions word for word, against `guide-set.dw`: the
\* same rule as the Dogwood guide prints it, gated on `Read::response`, which the guide glosses as
\* "successfully read the same document" (04-temporal-expressions.md).
\*
\* Every claim should HOLD here. If one breaks, the finding against `skill-set.dw` is not about
\* the event kind, and the comparison means nothing.
EXTENDS Integers, Sequences, FiniteSets, PolicyUnderTest

D == INSTANCE DogwoodSemantics WITH Cases <- << >>

(***************************************************************************)
(* THE SESSIONS. Alice, one document each, the Write last.                 *)
(*                                                                         *)
(*   deniedRead     she tries to read "restricted", which the set forbids; *)
(*                  the attempt is refused, then she writes it              *)
(*   failedRead     she reads doc1, allowed, but the call fails             *)
(*   completedRead  she reads doc1 and it completes                        *)
(*   noRead         she writes doc1 having read nothing                    *)
(***************************************************************************)
Doc(d) == [document |-> Str(d), user |-> Str("alice")]
Done   == [result |-> Bool(TRUE)]

ReadAsked(d, t)  == Ev("Read", "request", Doc(d), NoFields, t)
ReadDone(d, t)   == Ev("Read", "response", Doc(d), Done, t)
ReadFailed(d, t) == Ev("Read", "error", Doc(d), NoFields, t)
Write(d, t)      == Ev("Write", "request", Doc(d), NoFields, t)

Scenarios == {"deniedRead", "failedRead", "completedRead", "noRead"}

Session(s) ==
    CASE s = "deniedRead"    -> << ReadAsked("restricted", 1), ReadFailed("restricted", 2), Write("restricted", 3) >>
      [] s = "failedRead"    -> << ReadAsked("doc1", 1), ReadFailed("doc1", 2), Write("doc1", 3) >>
      [] s = "completedRead" -> << ReadAsked("doc1", 1), ReadDone("doc1", 2), Write("doc1", 3) >>
      [] OTHER               -> << Write("doc1", 1) >>

\* The decision for the LAST event of each session: the Write.
Allowed(s) == D!Decide(Session(s), Policies, Len(Session(s)), AllValues)

VARIABLE scenario
Init == scenario \in Scenarios
Next == UNCHANGED scenario
Spec == Init /\ [][Next]_scenario

(***************************************************************************)
(* THE CLAIMS.                                                             *)
(***************************************************************************)

\* A Read the set refused read nothing, so it cannot license a Write.
NoWriteAfterADeniedRead == scenario = "deniedRead" => ~Allowed(scenario)

\* Nor can a Read that was allowed but failed.
NoWriteAfterAFailedRead == scenario = "failedRead" => ~Allowed(scenario)

\* No Read at all, no Write.
NoWriteWithoutARead == scenario = "noRead" => ~Allowed(scenario)

\* The control: a completed Read DOES license the Write. Without this, a set that refused every
\* Write would pass the three claims above having tested nothing.
WriteAfterACompletedRead == scenario = "completedRead" => Allowed(scenario)

=============================================================================
