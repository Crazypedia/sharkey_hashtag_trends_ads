# Quick commands
PY?=.venv/bin/python
PIP?=.venv/bin/pip

venv:
	python -m venv .venv
	$(PIP) install -U pip

install: venv
	$(PIP) install -r requirements.txt

test: install
	$(PY) -m pytest

run-trends:
	$(PY) -m sharkey_ads.bubble_trends --select 10

run-uploads:
	$(PY) -m sharkey_ads.ads_stage_uploads

run-ads:
	# Set DRY_RUN=1 to preview payloads without creating/updating
	DRY_RUN?=0
	DRY_RUN=$(DRY_RUN) $(PY) -m sharkey_ads.ad_stage_create_ad

clean-ads:
	$(PY) -m sharkey_ads.clean_ads_folder --yes
