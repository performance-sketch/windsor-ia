"""
atualizar_dados.py
==================
Busca dados do Rezdy com paginacao e gera o index.html.
Armazena dataCriacao (booking date) e dataFulfillment (data do voo) separadamente.
Execute: python atualizar_dados.py
"""

import requests
import json
import re
import time
from datetime import datetime, timedelta
from collections import defaultdict

# ─── CONFIGURACAO ─────────────────────────────────────────────────────────────
CHAVE_API_REZDY   = "dc7f8d97256e484b8763a983ded2ba22"
URL_BASE_REZDY    = "https://api.rezdy.com/v1"
ARQUIVO_DASHBOARD = "index.html"
LIMITE_TOTAL      = 6000   # cobre ~12-14 meses de historico
# ──────────────────────────────────────────────────────────────────────────────

DIAS_PT = ["Segunda", "Terca", "Quarta", "Quinta", "Sexta", "Sabado", "Domingo"]

MESES_PT = {
    "01":"Jan","02":"Fev","03":"Mar","04":"Abr","05":"Mai","06":"Jun",
    "07":"Jul","08":"Ago","09":"Set","10":"Out","11":"Nov","12":"Dez"
}

def label_mes(ym):
    y, m = ym.split("-")
    return f"{MESES_PT.get(m, m)}/{y}"


def buscar_rezdy(endpoint, parametros=None):
    params = {"apiKey": CHAVE_API_REZDY, **(parametros or {})}
    resposta = requests.get(f"{URL_BASE_REZDY}/{endpoint}", params=params, timeout=20)
    resposta.raise_for_status()
    return resposta.json()


def buscar_todas_reservas():
    todas = []
    offset = 0
    while offset < LIMITE_TOTAL:
        lote = buscar_rezdy("bookings", {"limit": 100, "offset": offset})
        reservas = lote.get("bookings", [])
        if not reservas:
            break
        todas.extend(reservas)
        print(f"  Buscando... {len(todas)} reservas ({reservas[-1].get('dateCreated','')[:10]})")
        if len(reservas) < 100:
            break
        offset += 100
        time.sleep(0.1)
    return todas


def processar_reservas(reservas):
    receita_total = sum(r.get("totalAmount", 0) for r in reservas)
    total_pago    = sum(r.get("totalPaid",   0) for r in reservas)
    total_a_pagar = sum(r.get("totalDue",    0) for r in reservas)

    contagem_status = defaultdict(int)
    for r in reservas:
        contagem_status[r.get("status", "DESCONHECIDO")] += 1

    receita_por_produto = defaultdict(float)
    for r in reservas:
        for item in r.get("items", []):
            nome = item.get("productName", "Desconhecido")
            receita_por_produto[nome] += item.get("amount", 0)

    reservas_por_dia = defaultdict(int)
    for r in reservas:
        data = r.get("dateCreated", "")[:10]
        if data:
            reservas_por_dia[data] += 1
    ultimos_30 = dict(sorted(reservas_por_dia.items())[-30:])

    lista_tabela = []
    for r in reservas:
        itens  = r.get("items", [])
        item0  = itens[0] if itens else {}
        cb     = r.get("createdBy") or {}
        agente = (cb.get("firstName","") + " " + cb.get("lastName","")).strip() or "-"

        data_criacao_raw = r.get("dateCreated", "")
        data_criacao     = data_criacao_raw[:10] if data_criacao_raw else ""
        start_local      = item0.get("startTimeLocal", "") or ""
        data_fulfillment = start_local[:10] if start_local else ""
        hora_fulfillment = start_local[11:16] if len(start_local) >= 16 else ""

        lista_tabela.append({
            "numeroPedido":    r.get("orderNumber"),
            "status":          r.get("status"),
            "source":          (r.get("source") or "DESCONHECIDO").upper(),
            "agente":          agente,
            "nomeCliente":     r.get("customer", {}).get("name", "-"),
            "emailCliente":    r.get("customer", {}).get("email", "-"),
            "produto":         item0.get("productName", "-"),
            "quantidade":      item0.get("totalQuantity", 0),
            "dataCriacao":     data_criacao,
            "dataFulfillment": data_fulfillment,
            "horaFulfillment": hora_fulfillment,
            "valorTotal":      r.get("totalAmount", 0),
            "valorPago":       r.get("totalPaid",   0),
            "valorAPagar":     r.get("totalDue",    0),
            "moeda":           r.get("totalCurrency", "BRL"),
        })

    return {
        "total_reservas":      len(reservas),
        "receita_total":       round(receita_total, 2),
        "total_pago":          round(total_pago, 2),
        "total_a_pagar":       round(total_a_pagar, 2),
        "contagem_status":     dict(contagem_status),
        "receita_por_produto": {k: round(v, 2) for k, v in receita_por_produto.items()},
        "reservas_por_dia":    ultimos_30,
        "tabela":              lista_tabela,
    }


def computar_mensal(reservas):
    mensal = defaultdict(lambda: {
        "ordens": 0, "receitaTotal": 0.0, "receitaProdutos": 0.0,
        "receitaExtras": 0.0, "pago": 0.0,
        "porFonte": defaultdict(int),
        "porStatus": defaultdict(int),
    })
    for r in reservas:
        dc = r.get("dateCreated", "")[:7]
        if not dc:
            continue
        m = mensal[dc]
        m["ordens"]       += 1
        m["receitaTotal"] += r.get("totalAmount", 0)
        m["pago"]         += r.get("totalPaid", 0)
        src = (r.get("source") or "DESCONHECIDO").upper()
        m["porFonte"][src]           += 1
        m["porStatus"][r.get("status", "?")] += 1
        for item in r.get("items", []):
            cat = (item.get("extras") or [])
            m["receitaProdutos"] += item.get("amount", 0)

    resultado = []
    for ym in sorted(mensal.keys()):
        d = mensal[ym]
        resultado.append({
            "mes":             ym,
            "label":           label_mes(ym),
            "ordens":          d["ordens"],
            "receitaTotal":    round(d["receitaTotal"], 2),
            "receitaProdutos": round(d["receitaProdutos"], 2),
            "pago":            round(d["pago"], 2),
            "porFonte":        dict(d["porFonte"]),
            "porStatus":       dict(d["porStatus"]),
        })
    return resultado


def computar_por_fonte(reservas):
    pf = defaultdict(lambda: {"ordens": 0, "receita": 0.0, "confirmadas": 0, "pax": 0})
    for r in reservas:
        src = (r.get("source") or "DESCONHECIDO").upper()
        pf[src]["ordens"]  += 1
        pf[src]["receita"] += r.get("totalAmount", 0)
        if r.get("status") == "CONFIRMED":
            pf[src]["confirmadas"] += 1
            pax = sum(
                sum(q.get("value", 0) for q in item.get("quantities", []))
                for item in r.get("items", [])
            )
            pf[src]["pax"] += pax
    return {k: {**v, "receita": round(v["receita"], 2)} for k, v in pf.items()}


def computar_dia_semana(reservas):
    booking = [{
        "dia": DIAS_PT[i], "indice": i,
        "ordens": 0, "receita": 0.0, "confirmadas": 0
    } for i in range(7)]
    fulfil = [{
        "dia": DIAS_PT[i], "indice": i,
        "ordens": 0, "receita": 0.0, "confirmadas": 0
    } for i in range(7)]

    for r in reservas:
        dc = r.get("dateCreated", "")[:10]
        if dc:
            try:
                dow = datetime.strptime(dc, "%Y-%m-%d").weekday()
                booking[dow]["ordens"]  += 1
                booking[dow]["receita"] += r.get("totalAmount", 0)
                if r.get("status") == "CONFIRMED":
                    booking[dow]["confirmadas"] += 1
            except Exception:
                pass

        for item in r.get("items", []):
            stl = (item.get("startTimeLocal") or "")[:10]
            if stl and r.get("status") == "CONFIRMED":
                try:
                    dow = datetime.strptime(stl, "%Y-%m-%d").weekday()
                    fulfil[dow]["ordens"]  += 1
                    fulfil[dow]["receita"] += item.get("amount", 0)
                    fulfil[dow]["confirmadas"] += 1
                except Exception:
                    pass

    for d in booking:
        d["receita"] = round(d["receita"], 2)
    for d in fulfil:
        d["receita"] = round(d["receita"], 2)

    return booking, fulfil


def computar_por_semana(reservas, n_semanas=8):
    hoje  = datetime.now()
    lunes = hoje - timedelta(days=hoje.weekday())  # Monday this week
    semanas = []
    for i in range(n_semanas - 1, -1, -1):
        ini = lunes - timedelta(weeks=i)
        fim = ini + timedelta(days=6)
        semanas.append({
            "inicio":       ini.strftime("%Y-%m-%d"),
            "fim":          fim.strftime("%Y-%m-%d"),
            "label":        ini.strftime("%d/%m"),
            "booked":       0,
            "fulfilled":    0,
            "receitaBooked": 0.0,
        })

    for r in reservas:
        dc = r.get("dateCreated", "")[:10]
        for s in semanas:
            if dc and s["inicio"] <= dc <= s["fim"]:
                s["booked"]       += 1
                s["receitaBooked"] += r.get("totalAmount", 0)
        if r.get("status") != "CONFIRMED":
            continue
        for item in r.get("items", []):
            stl = (item.get("startTimeLocal") or "")[:10]
            if stl:
                for s in semanas:
                    if s["inicio"] <= stl <= s["fim"]:
                        s["fulfilled"] += 1

    for s in semanas:
        s["receitaBooked"] = round(s["receitaBooked"], 2)
    return semanas


def computar_lead_time_heatmap(reservas):
    """Matriz booking_mes x fulfillment_mes para confirmados."""
    matriz   = defaultdict(lambda: defaultdict(int))
    bm_set   = set()
    fm_set   = set()
    for r in reservas:
        if r.get("status") != "CONFIRMED":
            continue
        bm = r.get("dateCreated", "")[:7]
        if not bm:
            continue
        for item in r.get("items", []):
            stl = (item.get("startTimeLocal") or "")[:7]
            if stl:
                matriz[bm][stl] += 1
                bm_set.add(bm)
                fm_set.add(stl)

    return {
        "bookingMeses":  sorted(bm_set),
        "fulfillMeses":  sorted(fm_set),
        "dados":         {bm: dict(fm_d) for bm, fm_d in matriz.items()},
    }


def processar_produtos(produtos):
    resultado = []
    for p in produtos:
        precos = [o.get("price", 0) for o in p.get("priceOptions", [])]
        resultado.append({
            "nome":           p.get("name"),
            "precoAnunciado": p.get("advertisedPrice") or (min(precos) if precos else 0),
            "moeda":          p.get("currency", "BRL"),
            "duracaoMinutos": p.get("durationMinutes", 0),
            "imagem":         (p.get("images") or [{}])[0].get("mediumSizeUrl", ""),
        })
    return resultado


def atualizar_bloco_js(html, nome_constante, novo_valor_python):
    novo_json = json.dumps(novo_valor_python, ensure_ascii=False, indent=2)
    padrao = rf"(const {nome_constante}\s*=\s*)(\{{[\s\S]*?\}}|\[[\s\S]*?\])(\s*;)"
    def substituir(match):
        return match.group(1) + novo_json + match.group(3)
    novo_html, quantidade = re.subn(padrao, substituir, html)
    if quantidade == 0:
        print(f"  [AVISO] Constante '{nome_constante}' nao encontrada no HTML.")
    return novo_html


def main():
    agora = datetime.now().strftime("%d/%m/%Y %H:%M")
    print(f"\n=== Atualizando dashboard -- {agora} ===\n")

    print(f"Buscando reservas do Rezdy (ate {LIMITE_TOTAL})...")
    reservas = buscar_todas_reservas()
    print(f"  Total: {len(reservas)} reservas encontradas.")

    print("Buscando produtos do Rezdy...")
    dados_produtos = buscar_rezdy("products", {"limit": 50})
    produtos = dados_produtos.get("products", [])
    print(f"  {len(produtos)} produtos encontrados.")

    print("\nProcessando dados...")
    resumo_rezdy    = processar_reservas(reservas)
    lista_produtos  = processar_produtos(produtos)
    mensal          = computar_mensal(reservas)
    por_fonte       = computar_por_fonte(reservas)
    ds_booking, ds_fulfil = computar_dia_semana(reservas)
    por_semana      = computar_por_semana(reservas, n_semanas=8)
    lead_time       = computar_lead_time_heatmap(reservas)

    dados_rezdy_js = {
        "resumo":           resumo_rezdy,
        "mensal":           mensal,
        "porFonte":         por_fonte,
        "diaSemanaBooking": ds_booking,
        "diaSemanaFulfil":  ds_fulfil,
        "porSemana":        por_semana,
        "leadTimeHeatmap":  lead_time,
        "produtos":         lista_produtos,
        "dataAtualizacao":  datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
    }

    print(f"Lendo {ARQUIVO_DASHBOARD}...")
    with open(ARQUIVO_DASHBOARD, "r", encoding="utf-8") as f:
        html = f.read()

    print("Atualizando dados no HTML...")
    html = atualizar_bloco_js(html, "DADOS_REZDY_LIVE", dados_rezdy_js)
    html = re.sub(
        r'(id="dataRezdy">)[^<]*(</span>)',
        rf'\g<1>{agora}\g<2>',
        html
    )

    with open(ARQUIVO_DASHBOARD, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\nDashboard atualizado com sucesso!")
    print(f"  Reservas:     {resumo_rezdy['total_reservas']}")
    print(f"  Receita total: R$ {resumo_rezdy['receita_total']:,.2f}")
    print(f"  Periodo:      {resumo_rezdy['tabela'][-1]['dataCriacao']} a {resumo_rezdy['tabela'][0]['dataCriacao']}")
    print(f"  Meses:        {len(mensal)}")
    print(f"  Produtos:     {len(lista_produtos)}")
    print(f"\nAbra o arquivo: {ARQUIVO_DASHBOARD}\n")


if __name__ == "__main__":
    main()
