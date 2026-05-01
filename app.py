import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px

# 1. CONFIGURAZIONE PAGINA
st.set_page_config(page_title="Sofim Dashboard - BI", layout="wide")

def clean_numeric(x):
    if isinstance(x, str):
        try:
            return float(str(x).replace('.', '').replace(',', '.'))
        except:
            return 0.0
    return x

def style_delta_table(val):
    if isinstance(val, (int, float)):
        color = 'green' if val > 0 else 'red' if val < 0 else 'grey'
        return f'color: {color}; font-weight: bold'
    return ''

def shorten_name(name, limit=25):
    if len(name) > limit:
        return name[:limit-3] + "..."
    return name

# --- SIDEBAR: CARICAMENTO E MENU ---
st.sidebar.header("📂 Caricamento Dati")
file_dati = st.sidebar.file_uploader("1. Movimenti Contabili (CSV)", type="csv")
file_mappa = st.sidebar.file_uploader("2. Classificazione Conti (Excel)", type="xlsx")

st.sidebar.divider()
menu = st.sidebar.radio("Seleziona Analisi:", [
    "🏠 Dashboard di Controllo", 
    "💰 Analisi Ricavi", 
    "👥 Analisi Clienti",
    "🔍 Analisi Dettaglio"
])

if file_dati and file_mappa:
    # 2. CARICAMENTO E PREPARAZIONE DATI
    df = pd.read_csv(file_dati, sep=None, engine='python')
    df.columns = df.columns.str.strip()
    df_mappa = pd.read_excel(file_mappa)
    df_mappa.columns = df_mappa.columns.str.strip()
    
    # Normalizzazione Codici
    df['Codice Conto'] = df['Codice Conto'].astype(str).str.strip().str.replace('.0', '', regex=False)
    df_mappa['Codice Conto'] = df_mappa['Codice Conto'].astype(str).str.strip().str.replace('.0', '', regex=False)
    
    # Date e Tempi
    df['Data Operazione'] = pd.to_datetime(df['Data Operazione'], dayfirst=True, errors='coerce')
    df['Anno'] = df['Data Operazione'].dt.year
    df['Mese_Num'] = df['Data Operazione'].dt.month
    
    # Calcolo Importo Netto (Avere - Dare)
    df['Importo_Netto'] = df['Avere'].apply(clean_numeric).fillna(0) - df['Dare'].apply(clean_numeric).fillna(0)

    # Esclusione Chiusure
    mask_chiusura = df['Descrizione Causale Testata'].str.contains('CHIUSURA|APERTURA', case=False, na=False)
    df_reale = df[~mask_chiusura].copy()

    # Merge con Mappatura
    df_final = pd.merge(df_reale, df_mappa[['Codice Conto', 'Categoria', 'Tipo']], on='Codice Conto', how='left')
    df_final['Cat_Safe'] = df_final['Categoria'].fillna("NON MAPPATO").str.upper().str.strip()
    
    # Identificazione Ricavi (Globale)
    mask_ricavi_global = df_final['Cat_Safe'].str.contains('RICAV|VENDIT|ENTRAT', na=False)
    mesi_nomi = ["Gen", "Feb", "Mar", "Apr", "Mag", "Giu", "Lug", "Ago", "Set", "Ott", "Nov", "Dic"]

    # --- PAGINA 1: DASHBOARD DI CONTROLLO ---
    if menu == "🏠 Dashboard di Controllo":
        st.title("📊 Stato della Quadratura")
        
        st.subheader("📌 Riepilogo Caricamento")
        tab_riepilogo = df_final.groupby('Anno').agg({'Data Operazione': 'max', 'Codice Conto': 'count'}).reset_index()
        tab_riepilogo.columns = ['Anno', 'Ultima Registrazione', 'N. Registrazioni']
        tab_riepilogo['Ultima Registrazione'] = tab_riepilogo['Ultima Registrazione'].dt.strftime('%d/%m/%Y')
        st.table(tab_riepilogo)

        st.subheader("⚖️ Verifica Bilanci (Segno Avere - Dare)")
        anni_disp = sorted(df_final['Anno'].unique())
        prospetto = pd.DataFrame(columns=anni_disp)

        def get_saldo(keywords):
            cat_match = [c for c in df_final['Cat_Safe'].unique() if any(k in c for k in keywords)]
            return df_final[df_final['Cat_Safe'].isin(cat_match)].groupby('Anno')['Importo_Netto'].sum().reindex(anni_disp, fill_value=0)

        prospetto.loc['[+] Ricavi'] = get_saldo(['RICAV', 'VENDIT', 'ENTRAT'])
        prospetto.loc['[-] Costi'] = get_saldo(['COST', 'ACQUIST', 'USCIT'])
        prospetto.loc['(=) Risultato Economico'] = prospetto.loc['[+] Ricavi'] + prospetto.loc['[-] Costi']
        prospetto.loc['---'] = ""
        prospetto.loc['[+] Passività/Patrimonio'] = get_saldo(['PASSIV'])
        prospetto.loc['[-] Attività'] = get_saldo(['ATTIV'])
        prospetto.loc['(=) Saldo Patrimoniale'] = prospetto.loc['[+] Passività/Patrimonio'] + prospetto.loc['[-] Attività']
        prospetto.loc['----'] = ""
        prospetto.loc['SQUADRATURA TOTALE'] = prospetto.loc['(=) Risultato Economico'] + prospetto.loc['(=) Saldo Patrimoniale']
        
        st.dataframe(prospetto.style.format(lambda x: f"€ {x:,.2f}" if isinstance(x, (int, float)) else x), use_container_width=True)

    # --- PAGINA 2: ANALISI RICAVI ---
    elif menu == "💰 Analisi Ricavi":
        st.title("💰 BI - Gestione Ricavi")
        
        anni = sorted(df_final['Anno'].unique())
        if len(anni) < 1:
            st.warning("Dati insufficienti per l'analisi.")
        else:
            anno_sel = st.selectbox("Seleziona Anno di Analisi", anni, index=len(anni)-1)
            anno_prec = anno_sel - 1
            
            tab1, tab2, tab3 = st.tabs(["📋 Tabella Comparativa", "📈 Dettaglio Vendite", "🍰 Composizione Vendite"])
            
            with tab1:
                st.subheader(f"Confronto Conti Ricavi: {anno_sel} vs {anno_prec}")
                df_ric_all = df_final[mask_ricavi_global & (df_final['Anno'].isin([anno_sel, anno_prec]))]
                pivot_ricavi = df_ric_all.pivot_table(index=['Tipo', 'Descrizione Conto'], columns='Anno', values='Importo_Netto', aggfunc='sum').reset_index().fillna(0)
                if anno_sel not in pivot_ricavi.columns: pivot_ricavi[anno_sel] = 0.0
                if anno_prec not in pivot_ricavi.columns: pivot_ricavi[anno_prec] = 0.0
                pivot_ricavi['Var. Assoluta €'] = pivot_ricavi[anno_sel] - pivot_ricavi[anno_prec]
                pivot_ricavi['Var. %'] = (pivot_ricavi['Var. Assoluta €'] / pivot_ricavi[anno_prec].abs() * 100).replace([np.inf, -np.inf], 0).fillna(0)
                pivot_ricavi = pivot_ricavi.sort_values(['Tipo', anno_sel], ascending=[True, False])
                st.dataframe(pivot_ricavi.style.format({anno_prec: "€ {:,.2f}", anno_sel: "€ {:,.2f}", 'Var. Assoluta €': "€ {:,.2f}", 'Var. %': "{:+.1f}%"}).map(style_delta_table, subset=['Var. Assoluta €', 'Var. %']), use_container_width=True, hide_index=True)

            with tab2:
                st.subheader("Analisi Trend Temporale")
                mask_ve = df_final['Tipo'].isin(['VE', 'VE1'])
                df_ric_curr_base = df_final[mask_ricavi_global & mask_ve & (df_final['Anno'] == anno_sel)]
                df_ric_prev_base = df_final[mask_ricavi_global & mask_ve & (df_final['Anno'] == anno_prec)]
                
                col_t1, col_t2 = st.columns(2)
                with col_t1:
                    tipi_disp = sorted(list(set(df_ric_curr_base['Tipo'].unique()) | set(df_ric_prev_base['Tipo'].unique())))
                    tipi_scelti = st.multiselect("Filtra Tipi Ricavo", tipi_disp, default=tipi_disp, key="trend_tipi")
                with col_t2:
                    tipo_trend_radio = st.radio("Visualizzazione Trend:", ["Mensile", "Progressivo"], horizontal=True, key="trend_radio")
                    is_prog_trend = (tipo_trend_radio == "Progressivo")

                df_t_curr = df_ric_curr_base[df_ric_curr_base['Tipo'].isin(tipi_scelti)] if tipi_scelti else df_ric_curr_base
                df_t_prev = df_ric_prev_base[df_ric_prev_base['Tipo'].isin(tipi_scelti)] if tipi_scelti else df_ric_prev_base

                res_curr_num = df_t_curr.groupby('Mese_Num')['Importo_Netto'].sum().reindex(range(1, 13), fill_value=0)
                res_prev_num = df_t_prev.groupby('Mese_Num')['Importo_Netto'].sum().reindex(range(1, 13), fill_value=0)
                
                if is_prog_trend:
                    res_curr_num, res_prev_num = res_curr_num.cumsum(), res_prev_num.cumsum()

                trend_plot = pd.DataFrame({f"Fatturato {anno_prec}": res_prev_num.values, f"Fatturato {anno_sel}": res_curr_num.values}, index=[f"{i+1:02d}-{mesi_nomi[i]}" for i in range(12)])
                st.area_chart(trend_plot, height=300)

                st.divider()
                st.subheader("📑 Dettaglio Movimenti per Mese")
                cf1, cf2, cf3 = st.columns([1.5, 1.5, 2])
                with cf1:
                    tipo_analisi_mov = st.radio("Metodo lista:", ["Mensile", "Progressivo"], horizontal=True, key="mov_mode")
                with cf2:
                    elenco_conti = sorted(list(set(df_t_curr['Descrizione Conto'].unique()) | set(df_t_prev['Descrizione Conto'].unique())))
                    conti_mov = st.multiselect("Filtra Conti", elenco_conti, key="mov_conti")
                with cf3:
                    mesi_mov = st.multiselect("Seleziona Mese/i", mesi_nomi, default=[mesi_nomi[pd.Timestamp.now().month-1]] if pd.Timestamp.now().month <= 12 else ["Gen"], key="mov_mesi")

                if not mesi_mov: nums_mov = range(1, 13)
                else:
                    mese_indices = [mesi_nomi.index(m) + 1 for m in mesi_mov]
                    nums_mov = range(1, max(mese_indices) + 1) if tipo_analisi_mov == "Progressivo" else mese_indices

                d_curr = df_t_curr[df_t_curr['Mese_Num'].isin(nums_mov) & (df_t_curr['Descrizione Conto'].isin(conti_mov) if conti_mov else True)]
                d_prev = df_t_prev[df_t_prev['Mese_Num'].isin(nums_mov) & (df_t_prev['Descrizione Conto'].isin(conti_mov) if conti_mov else True)]
                
                cols_target = ['Data Operazione', 'Ragione Sociale', 'Descrizione Conto', 'Descrizione Riga', 'Importo_Netto']
                cols_view = [c for c in cols_target if c in df_final.columns]
                
                st.write(f"**🟢 Movimenti {anno_sel}**")
                if not d_curr.empty:
                    st.dataframe(d_curr[cols_view].sort_values('Data Operazione').style.format({'Importo_Netto': '€ {:,.2f}', 'Data Operazione': lambda t: t.strftime('%d/%m/%Y') if pd.notnull(t) else ""}), use_container_width=True, hide_index=True)
                else: st.info(f"Nessun dato per il {anno_sel}")

                st.write(f"**⚪ Movimenti {anno_prec}**")
                if not d_prev.empty:
                    st.dataframe(d_prev[cols_view].sort_values('Data Operazione').style.format({'Importo_Netto': '€ {:,.2f}', 'Data Operazione': lambda t: t.strftime('%d/%m/%Y') if pd.notnull(t) else ""}), use_container_width=True, hide_index=True)
                else: st.info(f"Nessun dato per il {anno_prec}")

            with tab3:
                st.subheader("🍰 Analisi Mix Vendite")
                col_c1, col_c2 = st.columns([1, 1])
                with col_c1:
                    mese_comp_sel = st.select_slider("Fino al Mese di:", options=mesi_nomi, value=mesi_nomi[pd.Timestamp.now().month-2] if pd.Timestamp.now().month > 1 else mesi_nomi[0])
                    idx_m = mesi_nomi.index(mese_comp_sel) + 1
                with col_c2:
                    prog_comp = st.checkbox("Analisi Progressiva (Cumulata)", value=True)
                
                mask_f = (df_final['Mese_Num'] <= idx_m) if prog_comp else (df_final['Mese_Num'] == idx_m)
                df_c = df_final[mask_ricavi_global & df_final['Tipo'].isin(['VE', 'VE1']) & mask_f]
                
                # --- PRIMA LA TABELLA ---
                st.subheader("📊 Dettaglio Valori e Variazioni")
                df_mix = df_c.pivot_table(index='Descrizione Conto', columns='Anno', values='Importo_Netto', aggfunc='sum').fillna(0).reset_index()
                
                if anno_sel in df_mix.columns and anno_prec in df_mix.columns:
                    df_mix['Var %'] = ((df_mix[anno_sel] / df_mix[anno_prec].replace(0, np.nan)) - 1) * 100
                    df_mix = df_mix.sort_values(anno_sel, ascending=False)
                    st.dataframe(df_mix.style.format({
                        anno_sel: "€ {:,.2f}", 
                        anno_prec: "€ {:,.2f}", 
                        'Var %': "{:+.1f}%"
                    }).map(style_delta_table, subset=['Var %']), use_container_width=True, hide_index=True)
                else:
                    st.dataframe(df_mix, use_container_width=True, hide_index=True)

                st.divider()

                # --- POI I GRAFICI ---
                st.subheader("🥧 Visualizzazione Mix Ricavi")
                col_p1, col_p2 = st.columns(2)
                
                def create_clean_pie(df_pie, title):
                    # Ordiniamo i dati per rendere il grafico più leggibile
                    df_pie = df_pie.sort_values('Importo_Netto', ascending=False)
                    fig = px.pie(df_pie, values='Importo_Netto', names='Descrizione Conto', title=title)
                    
                    # Ottimizzazione etichette esterne e linee di collegamento
                    fig.update_traces(
                        textposition='outside', 
                        textinfo='label+percent',
                        showlegend=False,
                        # Aumentiamo il pull (distacco) per creare spazio alle linee
                        pull=[0.05] * len(df_pie),
                        marker=dict(line=dict(color='#FFFFFF', width=2)),
                        # Forza la visualizzazione delle etichette anche se affollate
                        insidetextorientation='horizontal'
                    )
                    
                    fig.update_layout(
                        # Aumentiamo significativamente i margini laterali e verticali
                        margin=dict(t=80, b=80, l=120, r=120),
                        # Permettiamo alle etichette di sforare i margini calcolati automaticamente
                        autosize=True,
                        hoverlabel=dict(bgcolor="white")
                    )
                    return fig

                with col_p1:
                    df_p1 = df_c[df_c['Anno'] == anno_prec].groupby('Descrizione Conto')['Importo_Netto'].sum().reset_index()
                    if not df_p1.empty:
                        st.plotly_chart(create_clean_pie(df_p1, f"Mix Ricavi {anno_prec}"), use_container_width=True)
                    else: st.info(f"Dati {anno_prec} non disponibili.")

                with col_p2:
                    df_p2 = df_c[df_c['Anno'] == anno_sel].groupby('Descrizione Conto')['Importo_Netto'].sum().reset_index()
                    if not df_p2.empty:
                        st.plotly_chart(create_clean_pie(df_p2, f"Mix Ricavi {anno_sel}"), use_container_width=True)
                    else: st.info(f"Dati {anno_sel} non disponibili.")

    # --- PAGINA 3: ANALISI CLIENTI ---
    elif menu == "👥 Analisi Clienti":
        st.title("👥 BI - Analisi Clienti")
        
        anni = sorted(df_final['Anno'].unique())
        anno_sel = st.selectbox("Anno di riferimento", anni, index=len(anni)-1, key="clienti_anno")
        anno_prec = anno_sel - 1
        
        # Filtriamo solo ricavi e tipi VE/VE1 per i clienti
        df_clienti = df_final[mask_ricavi_global & df_final['Tipo'].isin(['VE', 'VE1'])].copy()
        
        # Pulizia nomi clienti se presente colonna
        nome_col = 'Ragione Sociale' if 'Ragione Sociale' in df_clienti.columns else 'Descrizione Riga'
        
        # Assicuriamoci che la colonna nome_col sia stringa e senza nulli per evitare errori di ordinamento
        df_clienti[nome_col] = df_clienti[nome_col].fillna("CLIENTE NON DEFINITO").astype(str)
        
        t1, t2, t3 = st.tabs(["🔝 Top Clienti", "📈 Trend per Cliente", "📈 Variazioni (Gain/Loss)"])
        
        # Preparazione Pivot Comune per t1 e t3
        pivot_cli = df_clienti[df_clienti['Anno'].isin([anno_sel, anno_prec])].pivot_table(
            index=nome_col, columns='Anno', values='Importo_Netto', aggfunc='sum'
        ).fillna(0).reset_index()
        
        if anno_sel not in pivot_cli.columns: pivot_cli[anno_sel] = 0.0
        if anno_prec not in pivot_cli.columns: pivot_cli[anno_prec] = 0.0
        
        pivot_cli['Delta €'] = pivot_cli[anno_sel] - pivot_cli[anno_prec]
        pivot_cli['Var %'] = (pivot_cli['Delta €'] / pivot_cli[anno_prec].abs() * 100).replace([np.inf, -np.inf], 0).fillna(0)
        
        with t1:
            st.subheader(f"Classifica Fatturato Clienti: {anno_sel} vs {anno_prec}")
            
            # Tabella ordinata
            df_tabella = pivot_cli.sort_values(anno_sel, ascending=False)
            
            st.dataframe(df_tabella.style.format({
                anno_sel: "€ {:,.2f}", 
                anno_prec: "€ {:,.2f}", 
                'Delta €': "€ {:,.2f}",
                'Var %': "{:+.1f}%"
            }).map(style_delta_table, subset=['Delta €', 'Var %']), use_container_width=True, hide_index=True)
            
            st.divider()
            
            # --- GRAFICO A BARRE ORIZZONTALI (FATTURATO) ---
            st.subheader(f"📊 Distribuzione Fatturato per Cliente ({anno_sel})")
            n_top = st.slider("Numero di clienti da visualizzare nel grafico", 5, 50, 20)
            
            df_chart = df_tabella.head(n_top).sort_values(anno_sel, ascending=True)
            
            fig_bar = px.bar(
                df_chart, 
                y=nome_col, 
                x=anno_sel,
                orientation='h',
                title=f"Top {n_top} Clienti per Fatturato {anno_sel}",
                labels={anno_sel: "Fatturato (€)", nome_col: "Cliente"},
                color=anno_sel,
                color_continuous_scale='Viridis',
                text_auto='.2s'
            )
            fig_bar.update_layout(yaxis={'categoryorder':'total ascending'}, height=max(400, n_top * 25))
            st.plotly_chart(fig_bar, use_container_width=True)
            
        with t2:
            st.subheader("Analisi Dettaglio per Cliente")
            clienti_lista = sorted([str(x) for x in df_clienti[nome_col].unique()])
            sel_clienti = st.multiselect("Seleziona Clienti da monitorare (tutto lo storico)", clienti_lista)
            
            if sel_clienti:
                df_sel_cli = df_clienti[df_clienti[nome_col].isin(sel_clienti) & (df_clienti['Anno'] == anno_sel)]
                
                # Trend mensile dei clienti selezionati
                trend_cli = df_sel_cli.groupby(['Mese_Num', nome_col])['Importo_Netto'].sum().unstack(fill_value=0).reindex(range(1, 13), fill_value=0)
                trend_cli.index = [f"{i:02d}-{mesi_nomi[i-1]}" for i in trend_cli.index]
                
                st.line_chart(trend_cli)
                
                # Tabella movimenti dettagliata per questi clienti
                st.write(f"🔍 **Movimenti del {anno_sel} per i Clienti selezionati**")
                cols_view = [c for c in ['Data Operazione', nome_col, 'Descrizione Riga', 'Importo_Netto'] if c in df_sel_cli.columns]
                st.dataframe(df_sel_cli[cols_view].sort_values('Data Operazione', ascending=False), use_container_width=True, hide_index=True)
            else:
                st.info("Seleziona uno o più clienti (anche di anni passati) per visualizzare il trend nell'anno corrente.")

        with t3:
            st.subheader(f"📈 Analisi Incrementi e Decrementi ({anno_sel} vs {anno_prec})")
            st.write("Questa vista evidenzia i clienti con la maggiore variazione monetaria (Delta €).")
            
            col_gain, col_loss = st.columns(2)
            
            n_rank = st.number_input("Mostra primi N:", 5, 30, 10)
            
            with col_gain:
                st.markdown("#### 🟢 Maggiori Incrementi")
                df_gain = pivot_cli[pivot_cli['Delta €'] > 0].sort_values('Delta €', ascending=False).head(n_rank)
                if not df_gain.empty:
                    fig_gain = px.bar(
                        df_gain.sort_values('Delta €', ascending=True),
                        y=nome_col,
                        x='Delta €',
                        orientation='h',
                        color_discrete_sequence=['#2ecc71'],
                        text_auto='.2s',
                        labels={'Delta €': 'Guadagno (€)', nome_col: 'Cliente'}
                    )
                    fig_gain.update_layout(height=max(300, n_rank * 35), margin=dict(l=0, r=0, t=30, b=0))
                    st.plotly_chart(fig_gain, use_container_width=True)
                else:
                    st.info("Nessun incremento rilevato.")

            with col_loss:
                st.markdown("#### 🔴 Maggiori Decrementi")
                df_loss = pivot_cli[pivot_cli['Delta €'] < 0].sort_values('Delta €', ascending=True).head(n_rank)
                if not df_loss.empty:
                    # Usiamo il valore assoluto per la visualizzazione grafica ma manteniamo l'etichetta negativa
                    df_loss['Delta_Abs'] = df_loss['Delta €'].abs()
                    fig_loss = px.bar(
                        df_loss.sort_values('Delta_Abs', ascending=True),
                        y=nome_col,
                        x='Delta_Abs',
                        orientation='h',
                        color_discrete_sequence=['#e74c3c'],
                        text_auto='.2s',
                        labels={'Delta_Abs': 'Perdita (€)', nome_col: 'Cliente'}
                    )
                    fig_loss.update_layout(height=max(300, n_rank * 35), margin=dict(l=0, r=0, t=30, b=0))
                    st.plotly_chart(fig_loss, use_container_width=True)
                else:
                    st.info("Nessun decremento rilevato.")

    # --- PAGINA 4: ANALISI DETTAGLIO ---
    elif menu == "🔍 Analisi Dettaglio":
        st.title("🔍 Esplorazione Categorie")
        cats = st.multiselect("Scegli categorie", sorted([str(c) for c in df_final['Cat_Safe'].unique()]))
        if cats:
            res = df_final[df_final['Cat_Safe'].isin(cats)].groupby(['Anno', 'Codice Conto', 'Descrizione Conto']).agg({'Importo_Netto': 'sum'}).reset_index()
            st.dataframe(res.style.format({'Importo_Netto': '€ {:,.2f}'}), use_container_width=True, hide_index=True)

else:
    st.title("📈 Sofim Financial Dashboard")
    st.info("Carica i file necessari nella sidebar per iniziare l'analisi.")