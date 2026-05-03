"""
Sofim Financial Dashboard — versione migliorata
Correzioni principali:
  - @st.cache_data su caricamento/elaborazione dati (performance)
  - create_clean_pie() spostata a livello modulo
  - Formattazione prospetto robusta su DataFrame misto
  - Fix indice mese corrente (gennaio non dava più -1)
  - Gestione colonne mancanti nel CSV
  - Refactoring in funzioni per manutenibilità
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px

try:
    import matplotlib
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

# ---------------------------------------------------------------------------
# CONFIGURAZIONE PAGINA
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Sofim Dashboard - BI", layout="wide")

MESI_NOMI = ["Gen", "Feb", "Mar", "Apr", "Mag", "Giu",
             "Lug", "Ago", "Set", "Ott", "Nov", "Dic"]

COLONNE_RICHIESTE = [
    "Data Operazione", "Codice Conto", "Descrizione Conto",
    "Descrizione Causale Testata", "Dare", "Avere",
]

# ---------------------------------------------------------------------------
# FUNZIONI DI UTILITÀ  (module-level, non dentro tab o blocchi if)
# ---------------------------------------------------------------------------

def clean_numeric(x) -> float:
    """Converte stringhe numeriche italiane (punti migliaia, virgola decimale)."""
    if isinstance(x, str):
        try:
            return float(x.strip().replace(".", "").replace(",", "."))
        except ValueError:
            return 0.0
    if pd.isna(x):
        return 0.0
    return float(x)


def style_delta(val):
    """Colora di verde/rosso valori numerici positivi/negativi."""
    if not isinstance(val, (int, float)):
        return ""
    if val > 0:
        return "color: green; font-weight: bold"
    if val < 0:
        return "color: red; font-weight: bold"
    return "color: grey"


def fmt_eur(x):
    """Formatta come Euro solo se numerico, altrimenti restituisce la stringa."""
    if isinstance(x, (int, float)) and not pd.isna(x):
        return f"€ {x:,.2f}"
    return str(x)


def create_clean_pie(df_pie: pd.DataFrame, title: str):
    """Grafico a torta (donut) pulito per il mix ricavi."""
    df_pie = (
        df_pie
        .dropna(subset=["Importo_Netto"])
        .pipe(lambda d: d[d["Importo_Netto"] > 0])
        .sort_values("Importo_Netto", ascending=False)
    )
    fig = px.pie(
        df_pie,
        values="Importo_Netto",
        names="Descrizione Conto",
        title=title,
        hole=0.4,
        color_discrete_sequence=px.colors.qualitative.Pastel,
    )
    fig.update_traces(
        textinfo="percent",
        textposition="auto",
        textfont_size=12,
        marker=dict(line=dict(color="#FFFFFF", width=1)),
    )
    fig.update_layout(
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=-0.5, xanchor="center", x=0.5),
        margin=dict(t=50, b=100, l=10, r=10),
        height=550,
    )
    return fig


# ---------------------------------------------------------------------------
# CARICAMENTO E PREPARAZIONE DATI  (con cache)
# ---------------------------------------------------------------------------

# In app.py, modifica così:
@st.cache_data(show_spinner="Caricamento movimenti contabili…")
def load_dati(file_bytes: bytes) -> pd.DataFrame:
    df = pd.read_csv(
        pd.io.common.BytesIO(file_bytes),
        sep=None,
        engine="python",
        dtype=str,
        encoding='latin1' # Forza la lettura compatibile con i gestionali Windows
    )
    df.columns = df.columns.str.strip()
    return df

@st.cache_data(show_spinner="Caricamento mappatura conti…")
def load_mappa(file_bytes: bytes) -> pd.DataFrame:
    df = pd.read_excel(pd.io.common.BytesIO(file_bytes))
    df.columns = df.columns.str.strip()
    return df


@st.cache_data(show_spinner="Elaborazione dati…")
def prepara_dati(dati_bytes: bytes, mappa_bytes: bytes) -> tuple[pd.DataFrame, list[str]]:
    """Carica, pulisce e unisce movimenti + mappatura. Restituisce (df_final, warnings)."""
    df = load_dati(dati_bytes)
    df_mappa = load_mappa(mappa_bytes)
    warnings = []

    # --- verifica colonne obbligatorie ---
    mancanti = [c for c in COLONNE_RICHIESTE if c not in df.columns]
    if mancanti:
        raise ValueError(f"Colonne mancanti nel CSV: {', '.join(mancanti)}")

    # --- normalizzazione codici conto ---
    for frame in (df, df_mappa):
        frame["Codice Conto"] = (
            frame["Codice Conto"].astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
        )

    # --- date ---
    df["Data Operazione"] = pd.to_datetime(df["Data Operazione"], dayfirst=True, errors="coerce")
    n_date_ko = df["Data Operazione"].isna().sum()
    if n_date_ko > 0:
        warnings.append(f"⚠️ {n_date_ko} righe con data non leggibile (ignorate).")
    df = df.dropna(subset=["Data Operazione"])

    df["Anno"] = df["Data Operazione"].dt.year.astype(int)
    df["Mese_Num"] = df["Data Operazione"].dt.month.astype(int)

    # --- importo netto ---
    df["Importo_Netto"] = (
        df["Avere"].apply(clean_numeric) - df["Dare"].apply(clean_numeric)
    )

    # --- esclusione aperture/chiusure ---
    mask_tecnica = df["Descrizione Causale Testata"].str.contains(
        r"CHIUSURA|APERTURA", case=False, na=False
    )
    df_reale = df[~mask_tecnica].copy()

    # --- merge mappatura ---
    cols_mappa = ["Codice Conto", "Categoria"]
    if "Tipo" in df_mappa.columns:
        cols_mappa.append("Tipo")
    else:
        warnings.append("⚠️ Colonna 'Tipo' assente nella mappatura — filtri per tipo disabilitati.")
        df_mappa["Tipo"] = "N/D"
        cols_mappa.append("Tipo")

    df_final = pd.merge(df_reale, df_mappa[cols_mappa], on="Codice Conto", how="left")
    df_final["Cat_Safe"] = df_final["Categoria"].fillna("NON MAPPATO").str.upper().str.strip()

    n_no_map = (df_final["Cat_Safe"] == "NON MAPPATO").sum()
    if n_no_map > 0:
        warnings.append(f"ℹ️ {n_no_map} righe con conto non mappato (categoria = NON MAPPATO).")

    return df_final, warnings


# ---------------------------------------------------------------------------
# PAGINA 1 — DASHBOARD DI CONTROLLO
# ---------------------------------------------------------------------------

def pagina_controllo(df_final: pd.DataFrame) -> None:
    st.title("📊 Stato della Quadratura")

    st.subheader("📌 Riepilogo Caricamento")
    tab_riepilogo = (
        df_final.groupby("Anno")
        .agg(ultima_reg=("Data Operazione", "max"), n_reg=("Codice Conto", "count"))
        .reset_index()
    )
    tab_riepilogo.columns = ["Anno", "Ultima Registrazione", "N. Registrazioni"]
    tab_riepilogo["Ultima Registrazione"] = tab_riepilogo["Ultima Registrazione"].dt.strftime("%d/%m/%Y")
    st.table(tab_riepilogo)

    st.subheader("⚖️ Verifica Bilanci (segno: Avere − Dare)")
    anni_disp = sorted(df_final["Anno"].unique())

    def get_saldo(keywords: list[str]) -> pd.Series:
        match = [c for c in df_final["Cat_Safe"].unique() if any(k in c for k in keywords)]
        return (
            df_final[df_final["Cat_Safe"].isin(match)]
            .groupby("Anno")["Importo_Netto"]
            .sum()
            .reindex(anni_disp, fill_value=0)
        )

    righe = {
        "[+] Ricavi":               get_saldo(["RICAV", "VENDIT", "ENTRAT"]),
        "[-] Costi":                get_saldo(["COST", "ACQUIST", "USCIT"]),
        "(=) Risultato Economico":  None,
        " ":                        None,          # separatore
        "[+] Passività/Patrimonio": get_saldo(["PASSIV"]),
        "[-] Attività":             get_saldo(["ATTIV"]),
        "(=) Saldo Patrimoniale":   None,
        "  ":                       None,          # separatore
        "SQUADRATURA TOTALE":       None,
    }

    prospetto = pd.DataFrame(index=list(righe.keys()), columns=anni_disp, dtype=object)
    for k, v in righe.items():
        if v is not None:
            prospetto.loc[k] = v.values

    prospetto.loc["(=) Risultato Economico"] = (
        prospetto.loc["[+] Ricavi"].astype(float) + prospetto.loc["[-] Costi"].astype(float)
    ).values
    prospetto.loc["(=) Saldo Patrimoniale"] = (
        prospetto.loc["[+] Passività/Patrimonio"].astype(float) + prospetto.loc["[-] Attività"].astype(float)
    ).values
    prospetto.loc["SQUADRATURA TOTALE"] = (
        prospetto.loc["(=) Risultato Economico"].astype(float)
        + prospetto.loc["(=) Saldo Patrimoniale"].astype(float)
    ).values

    # Formattazione robusta su DataFrame misto (stringhe + float)
    styled = prospetto.style.format(fmt_eur)
    st.dataframe(styled, use_container_width=True)


# ---------------------------------------------------------------------------
# PAGINA 2 — ANALISI RICAVI
# ---------------------------------------------------------------------------

def pagina_ricavi(df_final: pd.DataFrame, mask_ricavi: pd.Series) -> None:
    st.title("💰 BI - Gestione Ricavi")

    anni = sorted(df_final["Anno"].unique())
    if len(anni) < 1:
        st.warning("Dati insufficienti per l'analisi.")
        return

    anno_sel = st.selectbox("Seleziona Anno di Analisi", anni, index=len(anni) - 1)
    anno_prec = anno_sel - 1

    tab1, tab2, tab3 = st.tabs(["📋 Tabella Comparativa", "📈 Dettaglio Vendite", "🍰 Composizione Vendite"])

    # --- TAB 1: Tabella comparativa ---
    with tab1:
        st.subheader(f"Confronto Conti Ricavi: {anno_sel} vs {anno_prec}")
        df_ric_all = df_final[mask_ricavi & df_final["Anno"].isin([anno_sel, anno_prec])]

        has_tipo = "Tipo" in df_final.columns and df_final["Tipo"].ne("N/D").any()
        index_cols = ["Tipo", "Descrizione Conto"] if has_tipo else ["Descrizione Conto"]

        pivot = (
            df_ric_all
            .pivot_table(index=index_cols, columns="Anno", values="Importo_Netto", aggfunc="sum")
            .reset_index()
            .fillna(0)
        )
        for a in [anno_sel, anno_prec]:
            if a not in pivot.columns:
                pivot[a] = 0.0

        pivot["Var. Assoluta €"] = pivot[anno_sel] - pivot[anno_prec]
        pivot["Var. %"] = (
            (pivot["Var. Assoluta €"] / pivot[anno_prec].abs() * 100)
            .replace([np.inf, -np.inf], 0)
            .fillna(0)
        )
        pivot = pivot.sort_values([index_cols[0], anno_sel] if has_tipo else [anno_sel], ascending=False)

        fmt_cols = {anno_prec: "€ {:,.2f}", anno_sel: "€ {:,.2f}", "Var. Assoluta €": "€ {:,.2f}", "Var. %": "{:+.1f}%"}
        st.dataframe(
            pivot.style.format(fmt_cols).map(style_delta, subset=["Var. Assoluta €", "Var. %"]),
            use_container_width=True, hide_index=True,
        )

  # --- TAB 2: Dettaglio vendite / trend ---
    with tab2:
        st.subheader("📈 Analisi Temporale e Comparativa")

        # 1. Filtri Globali della Scheda
        has_tipo = "Tipo" in df_final.columns
        col_f1, col_f2 = st.columns(2)
        
        with col_f1:
            # Filtro Tipo ora selezionabile tra VE e VE1
            opzioni_tipo = ["VE", "VE1"] if has_tipo else []
            tipi_scelti = st.multiselect("Seleziona Tipo Ricavo:", opzioni_tipo, default=opzioni_tipo)
            mask_ve = df_final["Tipo"].isin(tipi_scelti) if tipi_scelti else pd.Series(True, index=df_final.index)
        
        with col_f2:
            # Selettore per la prima tabella e il grafico
            is_prog_globale = st.radio("Visualizzazione Totale:", ["Mensile", "Progressivo"], horizontal=True, key="radio_glob") == "Progressivo"

        # Preparazione Dati Base
        df_base = df_final[mask_ricavi & mask_ve].copy()

        # 2. Tabella Totale Vendite
        pivot_mesi = (
            df_base[df_base["Anno"].isin([anno_sel, anno_prec])]
            .pivot_table(index="Mese_Num", columns="Anno", values="Importo_Netto", aggfunc="sum")
            .reindex(range(1, 13), fill_value=0)
        )
        
        for a in [anno_sel, anno_prec]:
            if a not in pivot_mesi.columns:
                pivot_mesi[a] = 0.0

        if is_prog_globale:
            pivot_mesi = pivot_mesi.cumsum()

        pivot_mesi["Var. Assoluta €"] = pivot_mesi[anno_sel] - pivot_mesi[anno_prec]
        pivot_mesi["Var. %"] = ((pivot_mesi[anno_sel] - pivot_mesi[anno_prec]) / pivot_mesi[anno_prec].replace(0, np.nan).abs() * 100).fillna(0)
        pivot_mesi.index = [f"{i:02d} - {MESI_NOMI[i-1]}" for i in pivot_mesi.index]

        st.markdown(f"**Prospetto Totale Vendite ({'Progressivo' if is_prog_globale else 'Mensile'})**")
        st.dataframe(
            pivot_mesi.style.format({anno_prec: "€ {:,.2f}", anno_sel: "€ {:,.2f}", "Var. Assoluta €": "€ {:,.2f}", "Var. %": "{:+.1f}%"})
            .map(style_delta, subset=["Var. Assoluta €", "Var. %"]),
            use_container_width=True
        )

        st.markdown(f"**Trend Grafico: {anno_sel} vs {anno_prec}**")
        st.area_chart(pivot_mesi[[anno_prec, anno_sel]], height=250)

        st.divider()

        # 3. Analisi per Singolo Conto con opzione Progressiva distinta
        st.subheader("🔍 Analisi di Dettaglio per Conto")
        
        col_c1, col_c2 = st.columns([2, 1])
        with col_c1:
            conti_disponibili = sorted(df_base["Descrizione Conto"].unique())
            conto_scelto = st.selectbox("Seleziona un conto:", ["---"] + conti_disponibili)
        with col_c2:
            is_prog_conto = st.checkbox("Valori Progressivi (Conto)", value=False, key="check_prog_conto")

        if conto_scelto != "---":
            df_conto = df_base[df_base["Descrizione Conto"] == conto_scelto]
            pivot_conto = (
                df_conto[df_conto["Anno"].isin([anno_sel, anno_prec])]
                .pivot_table(index="Mese_Num", columns="Anno", values="Importo_Netto", aggfunc="sum")
                .reindex(range(1, 13), fill_value=0)
            )

            for a in [anno_sel, anno_prec]:
                if a not in pivot_conto.columns: pivot_conto[a] = 0.0

            if is_prog_conto:
                pivot_conto = pivot_conto.cumsum()

            pivot_conto["Var. Assoluta €"] = pivot_conto[anno_sel] - pivot_conto[anno_prec]
            pivot_conto["Var. %"] = ((pivot_conto[anno_sel] - pivot_conto[anno_prec]) / pivot_conto[anno_prec].replace(0, np.nan).abs() * 100).fillna(0)
            pivot_conto.index = [f"{i:02d} - {MESI_NOMI[i-1]}" for i in pivot_conto.index]

            st.dataframe(
                pivot_conto.style.format({anno_prec: "€ {:,.2f}", anno_sel: "€ {:,.2f}", "Var. Assoluta €": "€ {:,.2f}", "Var. %": "{:+.1f}%"})
                .map(style_delta, subset=["Var. Assoluta €", "Var. %"]),
                use_container_width=True
            )
        
        st.divider()

# 4. Riepilogo Fatturato per Cliente (Collegato al Conto selezionato)
        st.subheader("📑 Riepilogo per Cliente e Confronto Anni")
        
        if conto_scelto == "---":
            st.warning("⚠️ Seleziona un conto nella sezione superiore per visualizzare il dettaglio clienti.")
        else:
            c_mov1, c_mov2 = st.columns([1, 3])
            with c_mov1:
                is_prog_lista = st.checkbox("Metodo Progressivo", value=False, key="check_prog_lista")
            with c_mov2:
                mese_attuale_idx = max(pd.Timestamp.now().month - 2, 0)
                mesi_sel = st.multiselect("Filtra Mese/i per il riepilogo:", MESI_NOMI, default=[MESI_NOMI[mese_attuale_idx]])

            if mesi_sel:
                nums = [MESI_NOMI.index(m) + 1 for m in mesi_sel]
                range_mesi = range(1, max(nums) + 1) if is_prog_lista else nums
                
                # Usiamo lo stesso filtro conto della sezione precedente
                df_mov_filtered = df_base[
                    (df_base["Descrizione Conto"] == conto_scelto) & 
                    (df_base["Mese_Num"].isin(range_mesi))
                ]
                
                if not df_mov_filtered.empty:
                    col_cliente = "Ragione Sociale" if "Ragione Sociale" in df_mov_filtered.columns else "Descrizione Riga"
                    
                    # Pivot per confrontare Anno Corrente vs Anno Precedente per cliente
                    riepilogo_cli = (
                        df_mov_filtered[df_mov_filtered["Anno"].isin([anno_sel, anno_prec])]
                        .pivot_table(index=col_cliente, columns="Anno", values="Importo_Netto", aggfunc="sum")
                        .fillna(0)
                        .reset_index()
                    )
                    
                    # Controllo esistenza colonne anni
                    for a in [anno_sel, anno_prec]:
                        if a not in riepilogo_cli.columns:
                            riepilogo_cli[a] = 0.0
                    
                    # Calcolo variazioni
                    riepilogo_cli["Delta €"] = riepilogo_cli[anno_sel] - riepilogo_cli[anno_prec]
                    riepilogo_cli["Var %"] = (
                        (riepilogo_cli["Delta €"] / riepilogo_cli[anno_prec].replace(0, np.nan).abs() * 100)
                        .fillna(0)
                    )
                    
                    riepilogo_cli = riepilogo_cli.sort_values(anno_sel, ascending=False)

                    st.markdown(f"**Analisi Clienti per: {conto_scelto} ({'Progressivo' if is_prog_lista else 'Mesi selezionati'})**")
                    
                    st.dataframe(
                        riepilogo_cli.style.format({
                            anno_prec: "€ {:,.2f}", 
                            anno_sel: "€ {:,.2f}", 
                            "Delta €": "€ {:,.2f}", 
                            "Var %": "{:+.1f}%"
                        }).map(style_delta, subset=["Delta €", "Var %"]),
                        use_container_width=True, 
                        hide_index=True
                    )
                else:
                    st.info(f"Nessun dato trovato per il conto '{conto_scelto}' nei mesi selezionati.")
 
# --- TAB 3: Composizione vendite ---
    with tab3:
        st.subheader("🍰 Analisi Mix Vendite")
        col_c1, col_c2 = st.columns(2)
        with col_c1:
            mese_corrente_idx = max(pd.Timestamp.now().month - 2, 0)   # FIX: clamp a 0
            mese_comp = st.select_slider("Fino al Mese di:", options=MESI_NOMI, value=MESI_NOMI[mese_corrente_idx])
            idx_m = MESI_NOMI.index(mese_comp) + 1
        with col_c2:
            prog_comp = st.checkbox("Analisi Progressiva (Cumulata)", value=True)

        mask_f = (df_final["Mese_Num"] <= idx_m) if prog_comp else (df_final["Mese_Num"] == idx_m)
        mask_ve2 = df_final["Tipo"].isin(["VE", "VE1"]) if has_tipo else pd.Series(True, index=df_final.index)
        df_c = df_final[mask_ricavi & mask_ve2 & mask_f]

        st.subheader("🥧 Visualizzazione Mix Ricavi")
        col_p1, col_p2 = st.columns(2)
        for col_ui, anno, label in [(col_p1, anno_prec, f"Mix Ricavi {anno_prec}"), (col_p2, anno_sel, f"Mix Ricavi {anno_sel}")]:
            with col_ui:
                df_pie = df_c[df_c["Anno"] == anno].groupby("Descrizione Conto")["Importo_Netto"].sum().reset_index()
                if not df_pie.empty and df_pie["Importo_Netto"].sum() > 0:
                    st.plotly_chart(create_clean_pie(df_pie, label), use_container_width=True)
                else:
                    st.info(f"Dati {anno} non disponibili.")

        st.divider()
        st.subheader("📊 Tabella Comparativa Mix Ricavi con Incidenza %")
        df_mix = (
            df_c.pivot_table(index="Descrizione Conto", columns="Anno", values="Importo_Netto", aggfunc="sum")
            .fillna(0)
            .reset_index()
        )
        for a in [anno_sel, anno_prec]:
            if a not in df_mix.columns:
                df_mix[a] = 0.0

        tot_curr = df_mix[anno_sel].sum() or 1
        tot_prev = df_mix[anno_prec].sum() or 1
        col_pct_curr = f"% Su Tot {anno_sel}"
        col_pct_prev = f"% Su Tot {anno_prec}"
        df_mix[col_pct_curr] = df_mix[anno_sel] / tot_curr * 100
        df_mix[col_pct_prev] = df_mix[anno_prec] / tot_prev * 100
        df_mix["Variazione €"] = df_mix[anno_sel] - df_mix[anno_prec]
        df_mix["Var. %"] = (
            (df_mix["Variazione €"] / df_mix[anno_prec].abs() * 100)
            .replace([np.inf, -np.inf], 0)
            .fillna(0)
        )
        cols_ord = ["Descrizione Conto", anno_prec, col_pct_prev, anno_sel, col_pct_curr, "Variazione €", "Var. %"]
        df_mix = df_mix[cols_ord].sort_values(anno_sel, ascending=False)

        styler = df_mix.style.format({
            anno_prec: "€ {:,.2f}", anno_sel: "€ {:,.2f}",
            col_pct_prev: "{:.1f}%", col_pct_curr: "{:.1f}%",
            "Variazione €": "€ {:,.2f}", "Var. %": "{:+.1f}%",
        })
        if HAS_MATPLOTLIB:
            styler = styler.background_gradient(cmap="Blues", subset=[col_pct_prev, col_pct_curr])
        else:
            st.info("💡 Installa `matplotlib` per la colorazione delle percentuali.")
        styler = styler.map(style_delta, subset=["Variazione €", "Var. %"])
        st.dataframe(styler, use_container_width=True, hide_index=True)

# ---------------------------------------------------------------------------
# PAGINA 4 — ANALISI COSTI (Versione Finale - Senza errori di sintassi)
# ---------------------------------------------------------------------------

def pagina_costi(df_final: pd.DataFrame) -> None:
    st.title("💸 BI - Analisi Costi")

    anni = sorted(df_final["Anno"].unique())
    if len(anni) < 1:
        st.warning("Dati insufficienti per l'analisi.")
        return

    # 1. SETUP FILTRI
    anno_sel = st.selectbox("Seleziona Anno", anni, index=len(anni)-1, key="costi_anno")
    anno_prec = anno_sel - 1
    mask_costi = df_final["Cat_Safe"].str.contains(r"COST|ACQUIST|USCIT|PERSONALE", na=False)

    # Definizione Tabs
    t1, t2, t3, t4 = st.tabs(["📋 Tabella & Dettaglio", "📉 Trend Mensile", "📊 Incidenza Ricavi", "🎯 Pareto"])

    # --- TAB 1: Tabella Comparativa con Drill-Down SOPRA ---
    with t1:
        # 1. Spazio dinamico: questo contenitore si riempie solo al click
        placeholder_dettaglio = st.empty()
        
        st.subheader(f"Dettaglio Costi: {anno_sel} vs {anno_prec}")
        
        # Preparazione dati (già esistente nel tuo script)
        df_c = df_final[mask_costi & df_final["Anno"].isin([anno_sel, anno_prec])].copy()
        df_c["Valore_Costo"] = df_c["Dare"].apply(clean_numeric) - df_c["Avere"].apply(clean_numeric)
        
        pivot_costi = df_c.pivot_table(
            index=["Codice Conto", "Tipo", "Descrizione Conto"], 
            columns="Anno", 
            values="Valore_Costo", 
            aggfunc="sum"
        ).fillna(0).reset_index()

        for a in [anno_sel, anno_prec]:
            if a not in pivot_costi.columns: pivot_costi[a] = 0.0

        # 2. Rendering della tabella principale (Riepilogo)
        evento_selezione = st.dataframe(
            pivot_costi.style.format({
                anno_prec: "€ {:,.2f}", 
                anno_sel: "€ {:,.2f}"
            }),
            use_container_width=True, 
            hide_index=True, 
            on_select="rerun",           # Riattiva lo script al click
            selection_mode="single-row"  # Permette la selezione di una riga
        )

       # 3. Logica di visualizzazione Drill-Down (SOPRA la tabella)
        if len(evento_selezione.selection.rows) > 0:
            idx = evento_selezione.selection.rows[0]
            riga = pivot_costi.iloc[idx]
            codice_sel = riga["Codice Conto"]
            
            with placeholder_dettaglio.container():
                st.markdown(f"### 🔍 Analisi Movimenti: **{riga['Descrizione Conto']}**")
                
                # --- PREPARAZIONE DATI ---
                df_drill = df_final[
                    (df_final["Codice Conto"] == codice_sel) & 
                    (df_final["Anno"] == anno_sel)
                ].copy()

                # Convertiamo e calcoliamo l'Importo Netto
                df_drill["Importo_Netto"] = (
                    df_drill["Dare"].apply(clean_numeric) - df_drill["Avere"].apply(clean_numeric)
                )

                # ORDINAMENTO CRONOLOGICO: Fondamentale per il saldo e per la tua visualizzazione
                df_drill = df_drill.sort_values("Data Operazione", ascending=True)

                # Calcolo Saldo Progressivo cumulata nel tempo
                df_drill["Saldo Progressivo"] = df_drill["Importo_Netto"].cumsum()

                # Formattazione Data Operazione[cite: 1]
                df_drill["Data_Fmt"] = df_drill["Data Operazione"].dt.strftime("%d/%m/%Y")

                # Gestione colonne documentali[cite: 1]
                for col in ["Protocollo", "Numero Documento", "Data Documento"]:
                    if col not in df_drill.columns:
                        df_drill[col] = "-"

                if not df_drill.empty:
                    # Ordine colonne per la visualizzazione[cite: 1]
                    cols_view = [
                        "Data_Fmt", "Descrizione Causale Testata", "Protocollo", 
                        "Numero Documento", "Data Documento", "Importo_Netto", "Saldo Progressivo"
                    ]
                    
                    if "Descrizione Riga" in df_drill.columns:
                        cols_view.insert(2, "Descrizione Riga")

                    # VISUALIZZAZIONE: Rimosso il[::-1] per mantenere l'ordine dal meno al più recente[cite: 1]
                    st.dataframe(
                        df_drill[cols_view].style.format({
                            "Importo_Netto": "€ {:,.2f}", 
                            "Saldo Progressivo": "€ {:,.2f}"
                        }).map(style_delta, subset=["Importo_Netto"]), 
                        use_container_width=True, 
                        hide_index=True
                    )
                    
                    if st.button("Chiudi Dettaglio ❌"):
                        st.rerun()
                else:
                    st.info(f"Nessun movimento trovato per {riga['Descrizione Conto']}")
                
                st.divider()

    # --- TAB 2: Trend Mensile ---
    with t2:
        st.subheader("Andamento Temporale Costi")
        df_trend = df_c[df_c["Anno"].isin([anno_sel, anno_prec])].pivot_table(
            index="Mese_Num", columns="Anno", values="Valore_Costo", aggfunc="sum"
        ).reindex(range(1, 13), fill_value=0)
        
        df_trend.index = [f"{i:02d}-{MESI_NOMI[i-1]}" for i in df_trend.index]
        st.line_chart(df_trend)
        st.caption("Confronto andamento costi mensili tra l'anno selezionato e l'anno precedente.")

    # --- TAB 3: Incidenza su Ricavi ---
    with t3:
        mese_limite = st.session_state.get("mese_incidenza_new", 12)
        mask_periodo = df_final["Mese_Num"] <= mese_limite
        mask_ric = df_final["Cat_Safe"].str.contains(r"RICAV|VENDIT", na=False)
        tot_ric_sel = df_final[(df_final["Anno"] == anno_sel) & mask_ric & mask_periodo]["Importo_Netto"].abs().sum()
        tot_ric_prec = df_final[(df_final["Anno"] == anno_prec) & mask_ric & mask_periodo]["Importo_Netto"].abs().sum()

        m_col1, m_col2, m_col3 = st.columns([1, 1, 1])
        with m_col1:
            mese_limite = st.selectbox("Fino al mese di:", range(1, 13), index=mese_limite-1, format_func=lambda x: MESI_NOMI[x-1], key="mese_incidenza_new")
        with m_col2:
            st.metric(f"Fatturato {anno_sel}", f"€ {tot_ric_sel:,.0f}")
        with m_col3:
            st.metric(f"Fatturato {anno_prec}", f"€ {tot_ric_prec:,.0f}")

        df_c_periodo = df_c[df_c["Mese_Num"] <= mese_limite].copy()
        pivot_inc = df_c_periodo.pivot_table(index=["Codice Conto", "Descrizione Conto"], columns="Anno", values="Valore_Costo", aggfunc="sum").fillna(0).reset_index()
        
        if tot_ric_sel > 0:
            pivot_inc[f"Incidenza % {anno_sel}"] = (pivot_inc[anno_sel] / tot_ric_sel) * 100
            pivot_inc[f"Incidenza % {anno_prec}"] = (pivot_inc[anno_prec] / (tot_ric_prec if tot_ric_prec > 0 else 1)) * 100
            pivot_inc["Var. P.P."] = pivot_inc[f"Incidenza % {anno_sel}"] - pivot_inc[f"Incidenza % {anno_prec}"]
            
            df_view = pivot_inc[~pivot_inc["Descrizione Conto"].str.contains("RIMANENZE", case=False)].sort_values(f"Incidenza % {anno_sel}", ascending=False)
            
            st.dataframe(df_view[["Descrizione Conto", f"Incidenza % {anno_prec}", f"Incidenza % {anno_sel}", "Var. P.P."]].style.format({
                f"Incidenza % {anno_prec}": "{:.2f}%", f"Incidenza % {anno_sel}": "{:.2f}%", "Var. P.P.": "{:+.2f}"
            }).background_gradient(subset=["Var. P.P."], cmap="PiYG_r", vmin=-3, vmax=3)
              .map(lambda v: 'color: white; font-weight: bold;' if abs(v) > 1.5 else 'color: black;', subset=["Var. P.P."]), 
              use_container_width=True, hide_index=True)

            fig_inc = px.pie(df_view.head(10), values=f"Incidenza % {anno_sel}", names="Descrizione Conto", hole=0.4, template="plotly_white")
            fig_inc.update_traces(textposition='outside', textinfo='percent+label')
            fig_inc.update_layout(showlegend=False, height=600)
            st.plotly_chart(fig_inc, use_container_width=True)

    # --- TAB 4: Pareto ---
# --- TAB 4: Pareto ---
    with t4:
        st.subheader("Analisi di Pareto sui Costi (Regola 80/20)")
        st.info("Questa analisi identifica le voci di spesa che pesano maggiormente sul totale.")

        # 1. Preparazione dati
        mese_limite_pareto = st.session_state.get("mese_incidenza_new", 12)
        
        # Creiamo il subset di dati per l'anno selezionato partendo da pivot_inc (già calcolato in Tab 3)
        df_display = pivot_inc[
            ~pivot_inc["Descrizione Conto"].str.contains("RIMANENZE", case=False)
        ].copy()

        # Calcolo Totale e Percentuali Cumulate
        totale_costi_periodo = df_display[anno_sel].sum()
        
        if totale_costi_periodo > 0:
            df_display = df_display.sort_values(anno_sel, ascending=False)
            df_display["Peso %"] = (df_display[anno_sel] / totale_costi_periodo) * 100
            df_display["% Cumulata"] = df_display["Peso %"].cumsum()

            # 2. Definizione Classi A, B, C
            def assegna_classe(cum):
                if cum <= 80: return "A (Critico)"
                if cum <= 95: return "B (Medio)"
                return "C (Marginale)"
            
            df_display["Classe"] = df_display["% Cumulata"].apply(assegna_classe)

            # 3. Visualizzazione Grafica (Diagramma di Pareto)
            import plotly.graph_objects as go

            fig_pareto = go.Figure()

            # Barre per i costi singoli
            fig_pareto.add_trace(go.Bar(
                x=df_display["Descrizione Conto"],
                y=df_display[anno_sel],
                name="Costo per Voce",
                marker_color="#3498db"
            ))

            # Linea per la cumulata
            fig_pareto.add_trace(go.Scatter(
                x=df_display["Descrizione Conto"],
                y=df_display["% Cumulata"],
                name="% Cumulata",
                yaxis="y2",
                line=dict(color="#e74c3c", width=3),
                mode="lines+markers"
            ))

            fig_pareto.update_layout(
                title=f"Diagramma di Pareto - {anno_sel} (Fino al mese {mese_limite_pareto})",
                yaxis=dict(title="Importo (€)"),
                yaxis2=dict(title="Percentuale Cumulata (%)", overlaying="y", side="right", range=[0, 105]),
                showlegend=True,
                height=500,
                xaxis=dict(tickangle=-45)
            )

            st.plotly_chart(fig_pareto, use_container_width=True)

            # 4. Tabella Riassuntiva Classi
            st.markdown("### 📋 Classificazione delle Spese")
            
            st.dataframe(
                df_display[["Classe", "Codice Conto", "Descrizione Conto", anno_sel, "Peso %", "% Cumulata"]].style.format({
                    anno_sel: "€ {:,.2f}",
                    "Peso %": "{:.1f}%",
                    "% Cumulata": "{:.1f}%"
                }).map(lambda x: 'background-color: #f8d7da;' if x == "A (Critico)" else 
                                 ('background-color: #fff3cd;' if x == "B (Medio)" else ''), subset=["Classe"]),
                use_container_width=True, hide_index=True
            )
            
            voci_a = len(df_display[df_display["Classe"] == "A (Critico)"])
            st.success(f"**Insight:** Solo {voci_a} voci di costo rappresentano l'80% della tua spesa totale.")
        else:
            st.warning("Dati insufficienti per generare il diagramma di Pareto.")

# # ---------------------------------------------------------------------------
# PAGINA 4 — ANALISI CLIENTI (Versione Integrata con Saldo Crediti)
# ---------------------------------------------------------------------------

def pagina_clienti(df_final: pd.DataFrame, mask_ricavi: pd.Series) -> None:
    st.title("👥 BI - Analisi Clienti")

    anni = sorted(df_final["Anno"].unique())
    if len(anni) < 1:
        st.warning("Dati insufficienti per l'analisi.")
        return

    # 1. SETUP ANNI E FILTRI BASE
    anno_sel = st.selectbox("Anno di riferimento", anni, index=len(anni) - 1, key="clienti_anno")
    anno_prec = anno_sel - 1

    has_tipo = "Tipo" in df_final.columns and df_final["Tipo"].ne("N/D").any()
    mask_ve = df_final["Tipo"].isin(["VE", "VE1"]) if has_tipo else pd.Series(True, index=df_final.index)
    df_cli_ricavi = df_final[mask_ricavi & mask_ve].copy()

    nome_col = "Ragione Sociale" if "Ragione Sociale" in df_final.columns else "Descrizione Riga"
    df_cli_ricavi[nome_col] = df_cli_ricavi[nome_col].fillna("CLIENTE NON DEFINITO").astype(str)

    # 2. CALCOLO PIVOT FATTURATO
    pivot = (
        df_cli_ricavi[df_cli_ricavi["Anno"].isin([anno_sel, anno_prec])]
        .pivot_table(index=nome_col, columns="Anno", values="Importo_Netto", aggfunc="sum")
        .fillna(0)
        .reset_index()
    )
    for a in [anno_sel, anno_prec]:
        if a not in pivot.columns:
            pivot[a] = 0.0

    pivot["Delta €"] = pivot[anno_sel] - pivot[anno_prec]
    pivot["Var %"] = (
        (pivot["Delta €"] / pivot[anno_prec].abs() * 100)
        .replace([np.inf, -np.inf], 0)
        .fillna(0)
    )

    # 3. DEFINIZIONE SCHEDE
    t1, t2, t3, t4, t5 = st.tabs([
        "🔝 Top Clienti", 
        "📈 Trend per Cliente", 
        "📈 Variazioni (Gain/Loss)", 
        "🔄 Turnover Nuovi/Persi", 
        "💳 Crediti"
    ])

    with t1:
        st.subheader(f"Classifica Fatturato Clienti: {anno_sel} vs {anno_prec}")
        df_tab = pivot.sort_values(anno_sel, ascending=False)
        st.dataframe(
            df_tab.style
            .format({anno_sel: "€ {:,.2f}", anno_prec: "€ {:,.2f}", "Delta €": "€ {:,.2f}", "Var %": "{:+.1f}%"})
            .map(style_delta, subset=["Delta €", "Var %"]),
            use_container_width=True, hide_index=True,
        )

    with t2:
        st.subheader("Analisi Dettaglio per Cliente")
        clienti_lista = sorted(df_cli_ricavi[nome_col].unique().astype(str))
        sel_clienti = st.multiselect("Seleziona Clienti", clienti_lista)
        if sel_clienti:
            df_sel = df_cli_ricavi[df_cli_ricavi[nome_col].isin(sel_clienti) & (df_cli_ricavi["Anno"] == anno_sel)]
            trend = (
                df_sel.groupby(["Mese_Num", nome_col])["Importo_Netto"]
                .sum()
                .unstack(fill_value=0)
                .reindex(range(1, 13), fill_value=0)
            )
            trend.index = [f"{i:02d}-{MESI_NOMI[i-1]}" for i in trend.index]
            st.line_chart(trend)

    with t3:
        st.subheader("📈 Analisi Incrementi e Decrementi")
        n_rank = st.number_input("Mostra primi N:", 5, 30, 10)
        col_gain, col_loss = st.columns(2)
        with col_gain:
            st.markdown("#### 🟢 Maggiori Incrementi")
            df_gain = pivot[pivot["Delta €"] > 0].sort_values("Delta €", ascending=False).head(n_rank)
            if not df_gain.empty:
                st.plotly_chart(px.bar(df_gain.sort_values("Delta €"), y=nome_col, x="Delta €", orientation="h", color_discrete_sequence=["#2ecc71"]), use_container_width=True)
        with col_loss:
            st.markdown("#### 🔴 Maggiori Decrementi")
            df_loss = pivot[pivot["Delta €"] < 0].sort_values("Delta €").head(n_rank).copy()
            if not df_loss.empty:
                df_loss["Delta_Abs"] = df_loss["Delta €"].abs()
                st.plotly_chart(px.bar(df_loss.sort_values("Delta_Abs"), y=nome_col, x="Delta_Abs", orientation="h", color_discrete_sequence=["#e74c3c"]), use_container_width=True)

    with t4:
        st.subheader(f"🔄 Analisi Turnover Clienti ({anno_sel} vs {anno_prec})")
        nuovi = pivot[(pivot[anno_sel] > 0) & (pivot[anno_prec] <= 0)].sort_values(anno_sel, ascending=False)
        persi = pivot[(pivot[anno_sel] <= 0) & (pivot[anno_prec] > 0)].sort_values(anno_prec, ascending=False)
        c1, c2 = st.columns(2)
        with c1:
            st.success(f"🌟 Nuovi Clienti acquisiti: {len(nuovi)}")
            st.dataframe(nuovi[[nome_col, anno_sel]].style.format({anno_sel: "€ {:,.2f}"}), use_container_width=True, hide_index=True)
        with c2:
            st.error(f"⚠️ Clienti persi (Churn): {len(persi)}")
            st.dataframe(persi[[nome_col, anno_prec]].style.format({anno_prec: "€ {:,.2f}"}), use_container_width=True, hide_index=True)

    with t5:
        st.subheader("🏦 Analisi Crediti e Indici di Rotazione")
        
        # --- DRILL-DOWN PLACEHOLDER (Inizio della sezione) ---
        placeholder_drill_crediti = st.empty()

        # Configurazione e filtri
        tipo_view = st.radio(
            "Seleziona modalità di calcolo:",
            ["Saldo Progressivo (Esposizione Totale)", "Variazione Mensile (Flusso)", "Incidenza su Vendite (Ragguagliate)"],
            horizontal=True, key="radio_crediti_bi"
        )
        
        if "Tipo" in df_final.columns:
            mask_cli = df_final["Tipo"].str.upper().str.strip() == "CLI"
            df_crediti = df_final[mask_cli].copy()
            mask_ve_ve1 = df_final["Tipo"].str.upper().str.strip().isin(["VE", "VE1"])
            df_vendite = df_final[mask_ve_ve1].copy()
        else:
            st.error("Colonna 'Tipo' non trovata.")
            return

        if not df_crediti.empty:
            df_crediti["Saldo_Mov"] = df_crediti["Dare"].apply(clean_numeric) - df_crediti["Avere"].apply(clean_numeric)
            pivot_crediti_mesi = df_crediti.pivot_table(index="Mese_Num", columns="Anno", values="Saldo_Mov", aggfunc="sum").reindex(range(1, 13), fill_value=0.0)
            
            # Calcolo Valori per Visualizzazione
            df_long_crediti = pivot_crediti_mesi.melt(ignore_index=False, var_name="Anno", value_name="Flusso").reset_index()
            df_long_crediti = df_long_crediti.sort_values(["Anno", "Mese_Num"])
            df_long_crediti["Saldo_Progressivo"] = df_long_crediti.groupby("Anno")["Flusso"].cumsum()
            
            if tipo_view == "Saldo Progressivo (Esposizione Totale)":
                df_long_crediti["Valore_Visualizzato"] = df_long_crediti["Saldo_Progressivo"]
                fmt = "€ {:,.2f}"
            elif tipo_view == "Variazione Mensile (Flusso)":
                df_long_crediti["Valore_Visualizzato"] = df_long_crediti["Flusso"]
                fmt = "€ {:,.2f}"
            else: # Incidenza
                df_vendite["Valore_VE"] = df_vendite["Avere"].apply(clean_numeric) - df_vendite["Dare"].apply(clean_numeric)
                pivot_ve = df_vendite.pivot_table(index="Mese_Num", columns="Anno", values="Valore_VE", aggfunc="sum").reindex(range(1, 13), fill_value=0.0)
                df_ve_long = pivot_ve.melt(ignore_index=False, var_name="Anno", value_name="Flusso_VE").reset_index()
                df_ve_long["VE_Ragguagliata"] = (df_ve_long.groupby("Anno")["Flusso_VE"].cumsum() / df_ve_long["Mese_Num"]) * 12
                df_merged = pd.merge(df_long_crediti, df_ve_long, on=["Mese_Num", "Anno"])
                df_merged["Valore_Visualizzato"] = (df_merged["Saldo_Progressivo"] / df_merged["VE_Ragguagliata"].replace(0, np.nan)) * 100
                df_long_crediti = df_merged.fillna(0)
                fmt = "{:.2f}%"

            prospetto = df_long_crediti.pivot(index="Mese_Num", columns="Anno", values="Valore_Visualizzato").fillna(0)
            prospetto.index = [f"{i:02d} - {MESI_NOMI[i-1]}" for i in prospetto.index]
            col_confronto = [a for a in [anno_prec, anno_sel] if a in prospetto.columns]

            # --- RENDER TABELLA PRINCIPALE CON SELEZIONE ---
            st.markdown(f"**💰 Prospetto {tipo_view}** (Seleziona una riga per il dettaglio)")
            evento_sel = st.dataframe(
                prospetto[col_confronto].style.format(fmt).highlight_max(axis=0, color="#e3f2fd"),
                use_container_width=True, on_select="rerun", selection_mode="single-row", key="table_crediti"
            )

            # --- LOGICA DRILL-DOWN (Sopra la tabella grazie al placeholder) ---
            if len(evento_sel.selection.rows) > 0:
                idx_m = evento_sel.selection.rows[0] + 1
                with placeholder_drill_crediti.container():
                    st.info(f"🔍 Dettaglio Movimenti: **{MESI_NOMI[idx_m-1]} {anno_sel}**")
                    df_m = df_crediti[(df_crediti["Mese_Num"] == idx_m) & (df_crediti["Anno"] == anno_sel)]
                    if not df_m.empty:
                        res = df_m.groupby("Descrizione Conto")["Saldo_Mov"].sum().reset_index().sort_values("Saldo_Mov", ascending=False)
                        st.dataframe(res.style.format({"Saldo_Mov": "€ {:,.2f}"}), use_container_width=True, hide_index=True)
                        if st.button("Chiudi Dettaglio ❌"): st.rerun()
                    else: st.write("Nessun movimento diretto in questo mese.")
                    st.divider()

            # Grafico Trend
            fig_trend = px.line(df_long_crediti[df_long_crediti["Anno"].isin(col_confronto)], x="Mese_Num", y="Valore_Visualizzato", color="Anno", markers=True, template="plotly_white")
            fig_trend.update_xaxes(tickmode='array', tickvals=list(range(1, 13)), ticktext=MESI_NOMI)
            st.plotly_chart(fig_trend, use_container_width=True)


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main() -> None:
    st.sidebar.header("📂 Caricamento Dati")
    file_dati = st.sidebar.file_uploader("1. Movimenti Contabili (CSV)", type="csv")
    file_mappa = st.sidebar.file_uploader("2. Classificazione Conti (Excel)", type="xlsx")

    st.sidebar.divider()
    menu = st.sidebar.radio("Seleziona Analisi:", [
        "🏠 Dashboard di Controllo",
        "💰 Analisi Ricavi",
	"💸 Analisi Costi",
        "👥 Analisi Clienti",
        "🔍 Analisi Dettaglio",
    ])

    if not file_dati or not file_mappa:
        st.title("📈 Sofim Financial Dashboard")		
        st.info("👈 Carica i file nella sidebar per iniziare l'analisi.")
        if file_dati and not file_mappa:
            st.warning("Manca il file Excel di mappatura conti (colonne: Codice Conto, Categoria, Tipo).")
        return

    try:
        df_final, warnings = prepara_dati(file_dati.read(), file_mappa.read())
    except ValueError as e:
        st.error(str(e))
        return

    for w in warnings:
        st.sidebar.warning(w)

    mask_ricavi = df_final["Cat_Safe"].str.contains(r"RICAV|VENDIT|ENTRAT", na=False)

    if menu == "🏠 Dashboard di Controllo":
        pagina_controllo(df_final)
    elif menu == "💰 Analisi Ricavi":
        pagina_ricavi(df_final, mask_ricavi)
    elif menu == "💸 Analisi Costi":
        pagina_costi(df_final)
    elif menu == "👥 Analisi Clienti":
        pagina_clienti(df_final, mask_ricavi)
    elif menu == "🔍 Analisi Dettaglio":
        pagina_dettaglio(df_final)


if __name__ == "__main__":
    main()