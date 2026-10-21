VARIANTS = prompts/v1_baseline prompts/v2_ack_objection prompts/v3_indicative prompts/v4_concise prompts/v5_combined prompts/v0_sanity_bad
N ?= 30

.PHONY: test ab agreement regression gate results dashboard label

test:
	python -m pytest -q

ab:
	python ab_test.py --variants $(VARIANTS) --calls-per-persona $(N)

agreement:
	python eval/judge_agreement.py --rubrics rubric_v0.yaml rubric.yaml

regression:
	python -m callqc.regression run --variant prompts/$$(python -c "import yaml;print(yaml.safe_load(open('prompts/production.yaml'))['production'])")

gate:
	python eval/ci_gate.py

results: ab agreement
	python eval/make_results.py

dashboard:
	streamlit run apps/dashboard.py

label:
	streamlit run apps/label_app.py
