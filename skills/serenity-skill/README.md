# Serenity research skill

Manual, cross-market company and supply-chain research. Entry point:
[SKILL.md](SKILL.md); the desk routes it from `TOOLS.md`. It does not run in cron.

The skill links its research workflow, evidence standards, public sources and
risk boundaries under `references/`, with templates in `assets/`,
worked examples in `examples/`, and evaluation cases in `evals/test-cases.md`.

From the repository root:

```bash
python3 skills/serenity-skill/scripts/validate_skill.py skills/serenity-skill
python3 skills/serenity-skill/scripts/serenity_scorecard.py --template > my-company.json
python3 skills/serenity-skill/scripts/serenity_scorecard.py --format md my-company.json
```

Scripts use the Python standard library and local inputs. They do not place
trades or read credentials. Social sources are research leads; conclusions need
primary evidence. Source attribution remains in `references/research-sources.md`.
License: [MIT](LICENSE).
