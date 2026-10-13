# Build the technical report.
#
#   make          latexmk -pdf: full build including bibtex and cross-references
#   make quick    one pdflatex pass - fast, but citations show as [?]
#   make clean    remove build artefacts, keep the PDF
#   make distclean  remove the PDF too
#
# pdflatex-only and no packages outside the base TeX Live collections, so this
# builds on a minimal install (written against TinyTeX).

DOC := bhoonidhi-processes

# Reproducible build. pdfTeX stamps /CreationDate and \today from the clock,
# so rebuilding produced a byte-different PDF every time - and because the PDF
# is committed (a marker should not have to run LaTeX to read the report),
# `make report` left the working tree dirty. SOURCE_DATE_EPOCH plus
# FORCE_SOURCE_DATE pins both. Bump this when the report is revised.
#   1791849600 = 2026-10-13T00:00:00Z
export SOURCE_DATE_EPOCH := 1791849600
export FORCE_SOURCE_DATE := 1
SRC := $(DOC).tex preamble.tex refs.bib $(wildcard sections/*.tex)

.PHONY: all quick clean distclean view

all: $(DOC).pdf

$(DOC).pdf: $(SRC)
	@command -v latexmk >/dev/null 2>&1 || { \
	  echo "latexmk not found - falling back to pdflatex + bibtex"; \
	  pdflatex -interaction=nonstopmode $(DOC).tex >/dev/null; \
	  bibtex $(DOC) >/dev/null 2>&1 || true; \
	  pdflatex -interaction=nonstopmode $(DOC).tex >/dev/null; \
	  pdflatex -interaction=nonstopmode $(DOC).tex >/dev/null; \
	  exit 0; }
	latexmk -pdf -interaction=nonstopmode -halt-on-error $(DOC).tex

quick: ## one pass, no bibliography
	pdflatex -interaction=nonstopmode -halt-on-error $(DOC).tex

clean:
	rm -f $(DOC).aux $(DOC).bbl $(DOC).blg $(DOC).fdb_latexmk $(DOC).fls \
	      $(DOC).log $(DOC).out $(DOC).toc $(DOC).synctex.gz
	rm -f sections/*.aux

distclean: clean
	rm -f $(DOC).pdf

view: all
	xdg-open $(DOC).pdf 2>/dev/null || open $(DOC).pdf 2>/dev/null || true
