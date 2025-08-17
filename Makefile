# Quick commands
PY?=.venv/bin/python
PIP?=.venv/bin/pip

venv:
	python -m venv .venv
	$(PIP) install -U pip

install: venv
	$(PIP) install -r requirements.txt

run-trends:
	$(PY) _1_bubble_trends.py --select 10

run-uploads:
	$(PY) _2_ads_stage_uploads.py

run-ads:
	# Set DRY_RUN=1 to preview payloads without creating/updating
	DRY_RUN?=0
	DRY_RUN=$(DRY_RUN) $(PY) _3_ad_stage_create_ad.py

clean-ads:
	$(PY) clean_ads_folder.py --yes
