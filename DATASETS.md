# Datasets

DocuSort is trained on public datasets of real documents. They are **not redistributed** in this
repository; `src/build_dataset.py` builds the training set from your own clones of the sources below.
Check each licence before any use beyond research and learning.

| Type | Source | Where to get it | Licence / terms |
|---|---|---|---|
| Receipt or invoice | ICDAR 2019 SROIE, 626 scanned receipts (OCR text) | github.com/zzzDavid/ICDAR-2019-SROIE | Released for the ICDAR 2019 competition, research use; repository code MIT |
| Contract | CUAD v1, 510 commercial contracts | github.com/TheAtticusProject/cuad | CC BY 4.0 |
| Resume | resume_corpus (resumes from indeed.com) | github.com/florex/resume_corpus | No licence stated; research use |
| Email | Enron email corpus, non-spam messages | github.com/MWiechmann/enron_spam_data | Enron data is public (released by FERC); repository GPL-3.0 |
| News article | BBC News dataset, 2,225 articles (Greene & Cunningham, 2006) | github.com/suraj-deshmukh/BBC-Dataset-News-Classification | Research use |
| Research paper | SciTLDR full text | github.com/allenai/scitldr | Apache 2.0 |
| Research paper | PubMed 20k RCT abstracts | github.com/Franck-Dernoncourt/pubmed-rct | No licence stated; abstracts from PubMed |
| Form | FUNSD, 199 scanned forms | guillaumejaume.github.io/FUNSD | Non-commercial research and education |
| Medical report | MTSamples transcriptions | github.com/socd06/medical-nlp (mtsamples.csv) | Collected from mtsamples.com; repository GPL-3.0 |

Used only for testing (never for training):

| Source | Where to get it | Licence / terms |
|---|---|---|
| AG News articles | github.com/mhjabreel/CharCnn_Keras (data/ag_news_csv) | Academic, non-commercial |
| invoice2data sample invoices | github.com/invoice-x/invoice2data | MIT |

## Rebuild and retrain

```bash
mkdir sources && cd sources
for r in zzzDavid/ICDAR-2019-SROIE TheAtticusProject/cuad florex/resume_corpus MWiechmann/enron_spam_data \
         suraj-deshmukh/BBC-Dataset-News-Classification allenai/scitldr Franck-Dernoncourt/pubmed-rct \
         guillaumejaume/FUNSD socd06/medical-nlp mhjabreel/CharCnn_Keras invoice-x/invoice2data; do
  git clone --depth 1 https://github.com/$r
done
cd ..
pip install -r requirements-train.txt          # pdftotext (poppler-utils) is also needed for the invoices
python src/build_dataset.py --sources sources  # writes data/documents.csv and data/outside_test.csv
python src/train.py                            # trains, evaluates, writes models/ and reports/metrics.json
python src/evaluate_fields.py --sources sources
python src/evaluate_sensitive.py
```

## Sample files

`samples/receipt-scan.jpg` is receipt 002 from SROIE. The contract sample is the first part of a
CUAD contract. The invoice, resume and email samples were written for this project; their names
and numbers are made up.
