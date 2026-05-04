from __future__ import annotations
import argparse
from appgen.db import init_db
from appgen.repo import list_ideas
from appgen.services.exporter import export_to_appcreator
from appgen.services.generator import generate_ideas
from appgen.services.meta import analyze_meta
from appgen.services.stages import final_review, plan_generate


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m appgen.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_gen = sub.add_parser("generate")
    p_gen.add_argument("--seed", default="")
    p_gen.add_argument("--count", type=int, default=5)

    p_list = sub.add_parser("list")
    p_list.add_argument("--top", type=int, default=20)

    p_plan = sub.add_parser("plan")
    p_plan.add_argument("--idea", required=True)

    p_review = sub.add_parser("review")
    p_review.add_argument("--idea", required=True)

    sub.add_parser("meta-analyze")

    p_export = sub.add_parser("export-appcreator")
    p_export.add_argument("--idea", required=True)

    args = parser.parse_args()
    init_db()

    if args.cmd == "generate":
        print(generate_ideas([], args.seed, args.count, {}))
    elif args.cmd == "list":
        for i in list_ideas(sort="score")[: args.top]:
            print(i["id"], i["title"], (i.get("scores") or {}).get("overall_score"))
    elif args.cmd == "plan":
        print(plan_generate(args.idea))
    elif args.cmd == "review":
        print(final_review(args.idea))
    elif args.cmd == "meta-analyze":
        print(analyze_meta())
    elif args.cmd == "export-appcreator":
        print(export_to_appcreator(args.idea))


if __name__ == "__main__":
    main()
