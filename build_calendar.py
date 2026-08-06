# -*- coding: utf-8 -*-
"""
Gera o index.html do Calendário de Resultados (B3) automaticamente.
Roda no GitHub Actions (com internet). Estratégia robusta:
  1. Carrega seed.csv (base auditada, commitada no repo).
  2. Tenta coletar a agenda atual da StatusInvest. Se vier saudável
     (>= MIN_ROWS linhas válidas), substitui a base pela coletada.
     Se falhar, mantém a seed (a página nunca quebra).
  3. Aplica overrides.csv (correções auditadas que SEMPRE prevalecem).
  4. Injeta os dados no template.html e escreve index.html.
  5. Reescreve seed.csv com a base efetiva (para virar histórico/versionado).
"""
import csv, json, re, sys, datetime, io

SRC_URL   = "https://statusinvest.com.br/acoes/agenda-de-resultados"
MIN_ROWS  = 100          # abaixo disso, considera coleta falha e mantém a seed
TEMPLATE  = "template.html"
SEED      = "seed.csv"
OVERRIDES = "overrides.csv"
OUT       = "index.html"

MESES = {1:"Janeiro",2:"Fevereiro",3:"Marco",4:"Abril",5:"Maio",6:"Junho",
         7:"Julho",8:"Agosto",9:"Setembro",10:"Outubro",11:"Novembro",12:"Dezembro"}

TICKER_RE = re.compile(r"\b([A-Z]{4}\d{1,2})\b")
DATE_RE   = re.compile(r"\b(\d{2}/\d{2}/\d{4})\b")


def load_csv(path):
    out = {}
    try:
        with open(path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                t = (row.get("ticker") or "").strip().upper()
                if not t:
                    continue
                out[t] = ((row.get("empresa") or "").strip(),
                          (row.get("data") or "").strip())
    except FileNotFoundError:
        pass
    return out


def scrape():
    """Coleta a agenda da StatusInvest. Retorna dict ticker->(empresa,data) ou {}."""
    try:
        import requests
        from bs4 import BeautifulSoup
    except Exception as e:
        print(f"[scrape] libs indisponiveis: {e}", file=sys.stderr)
        return {}
    headers = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/124.0 Safari/537.36"),
        "Accept-Language": "pt-BR,pt;q=0.9",
    }
    try:
        r = requests.get(SRC_URL, headers=headers, timeout=40)
        r.raise_for_status()
    except Exception as e:
        print(f"[scrape] request falhou: {e}", file=sys.stderr)
        return {}
    soup = BeautifulSoup(r.text, "html.parser")
    found = {}

    def consider(text_cells):
        blob = " ".join(text_cells)
        tk = TICKER_RE.search(blob)
        dt = DATE_RE.search(blob)
        if not (tk and dt):
            return
        ticker = tk.group(1)
        data = dt.group(1)
        cand = [c.strip() for c in text_cells
                if c and c.strip().upper() != ticker
                and not DATE_RE.search(c) and re.search(r"[A-Za-zÀ-ÿ]", c)]
        empresa = max(cand, key=len).strip() if cand else ticker
        empresa = re.sub(r"\s+", " ", empresa)[:80]
        found.setdefault(ticker, (empresa, data))

    for tr in soup.find_all("tr"):
        cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
        if cells:
            consider(cells)
    if len(found) < MIN_ROWS:
        for el in soup.find_all(True):
            txt = el.get_text(" ", strip=True)
            if TICKER_RE.search(txt) and DATE_RE.search(txt) and len(txt) < 160:
                consider([txt])

    print(f"[scrape] linhas validas coletadas: {len(found)}", file=sys.stderr)
    return found


def build():
    base = load_csv(SEED)
    print(f"[build] seed: {len(base)} empresas", file=sys.stderr)

    scraped = scrape()
    if len(scraped) >= MIN_ROWS:
        print(f"[build] usando dados coletados ({len(scraped)})", file=sys.stderr)
        base = scraped
    else:
        print(f"[build] coleta insuficiente ({len(scraped)}); mantendo seed", file=sys.stderr)

    overrides = load_csv(OVERRIDES)
    for t, (nm, d) in overrides.items():
        base[t] = (nm or base.get(t, ("", ""))[0], d)
    print(f"[build] overrides aplicados: {len(overrides)}", file=sys.stderr)

    rows = []
    for t, (nm, d) in base.items():
        m = re.match(r"(\d{2})/(\d{2})/(\d{4})", d)
        if not m:
            continue
        dd, mm, yy = int(m.group(1)), int(m.group(2)), int(m.group(3))
        rows.append({"ticker": t, "empresa": nm, "data": d,
                     "iso": f"{yy:04d}-{mm:02d}-{dd:02d}",
                     "dia": dd, "mes": mm, "ano": yy, "tipo": "ITR - 2T26"})
    rows.sort(key=lambda r: (r["iso"], r["ticker"]))

    now = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=3)
    snapshot = now.strftime("%d/%m/%Y")
    tri = "2T26"

    meta = {"snapshot": snapshot, "trimestre": tri,
            "fonte": "StatusInvest - Agenda de Resultados",
            "fonteUrl": SRC_URL, "total": len(rows), "meses": MESES}

    tpl = open(TEMPLATE, encoding="utf-8").read()
    data_js = ("window.EARNINGS = " + json.dumps(rows, ensure_ascii=False) + ";\n"
               "window.META = " + json.dumps(meta, ensure_ascii=False) + ";\n")
    out = tpl.replace("__DATA__", data_js)
    if "__DATA__" in out:
        print("[build] ERRO: placeholder __DATA__ nao substituido", file=sys.stderr)
        sys.exit(1)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(out)
    print(f"[build] {OUT} gerado com {len(rows)} empresas (snapshot {snapshot})")

    with open(SEED, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ticker", "empresa", "data"])
        for r in rows:
            w.writerow([r["ticker"], r["empresa"], r["data"]])

    if len(rows) == 0:
        sys.exit(1)


if __name__ == "__main__":
    build()
