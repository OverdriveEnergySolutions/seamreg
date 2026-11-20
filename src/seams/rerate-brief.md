# Risk re-rating brief

Your packet lists seams from this repo's registry: knowledge kept in two or more files that must agree.
Each one has a risk that a quicker review set. Set each seam's risk again, from what actually breaks
when one copy changes and the others do not.

**Read only.** Your output file is the only file you write. Do not edit the repo or its git state, and
do not run its code. Stay inside the repo root, plus your packet, this brief and your output file.

## The scale
- **high**: drift would silently produce wrong results, lose or corrupt data, open a security gap
  (authentication, authorization, a limit that guards money or abuse), or misdrive hardware.
- **medium**: drift would cause a visible bug or a broken feature that someone would report.
- **low**: drift is cosmetic, or a test, a type check or a user would catch it fast.

## For each seam
1. Read its must_agree, consequence and drift. Then open the copies where you need to: who calls this
   code, what a user or an operator sees, and whether anything would fail loudly.
2. Ask: when one copy changes alone, what is the worst likely result, and would anyone notice?
   Silent and wrong is high. Loud and wrong is medium. Cosmetic or caught at once is low.
3. A seam about who may do what (sign-up, sign-in, roles, API access, plan limits) is high unless the
   copies guard nothing that matters. Do not lower a risk only because the copies agree today: the risk
   is about what drift would do, not whether it has happened.
4. Keep the current risk when it is right. Change it only with a reason you can state in one sentence.

## Output
Write a JSON array to your output file, one object per seam in the packet, in packet order:

```json
[{"id": "shipping-carrier-codes", "risk": "medium", "reason": "An order with a carrier one list lacks fails visibly at checkout."}]
```

Use each seam's id exactly as the packet gives it. After you write the file, read it back and make sure
it parses as JSON.

## Final reply
Under 100 words: the output path, how many risks you changed, and the seams you raised to high.
