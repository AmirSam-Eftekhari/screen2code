## What and why

## Checklist
- [ ] Tests added or updated; `python -m unittest discover -s tests -t .` passes
- [ ] No assertion was weakened to make a test pass
- [ ] IR/schema changes update docs/IR_SPEC.md, the golden fixture, and `schema/ir-0.1.schema.json`
- [ ] Security rules respected (confined writes, no execution of generated code)
- [ ] Docs match behaviour; experimental features are labelled
