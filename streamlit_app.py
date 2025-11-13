# === Importación de librerías ===
import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime

# === CONFIGURACIÓN INICIAL ===
st.set_page_config(page_title="Control de Mantenimientos", layout="wide")
st.title(" Auditoría Ejecución Especialidades Mtto Preventivo")

# === CONSTANTES ===
ARCHIVO = "libroTest.xlsx"
HOJA = "Hoja2"

# Nombres de columnas
COL_ESPECIALIDAD = "SUB_ESPECIALIDAD"
COL_SITE = "Site Id Name"
COL_PRIORIDAD = "Site Priority"
COL_CONTRATISTA = "Contratista Sitio"
COL_ESTADO = "ESTADO"
COL_FECHA = "2_MES_PROGRA"
COL_FLM_ESPECIFICO = "SUP_FLM_2"

ESPECIALIDADES = [
    "AA", "GE-TTA-TK", "IE", "SE-LT", "REC-BB", "TX", "TX-BH",
    "UPS", "INV-AVR", "LT", "RADIO", "SOL-EOL"
]

MESES = {
    'ene':'01', 'feb':'02', 'mar':'03', 'abr':'04', 'may':'05', 'jun':'06',
    'jul':'07', 'ago':'08', 'set':'09', 'oct':'10', 'nov':'11', 'dic':'12'
}

# === FUNCIONES AUXILIARES ===
def convertir_mes_ano(valor):
    """Convierte 'ene-23' a '2023-01'"""
    if isinstance(valor, str) and '-' in valor:
        mes_abrev, anio = valor.split('-')
        mes = MESES.get(mes_abrev.strip())
        if mes:
            return f"20{anio.strip()}-{mes}"
    return "Fecha desconocida"

def calcular_score_riesgo(site, eliminadas, mantenimientos_perdidos, diferencias_mtto, prioridad_df):
    """
    Calcula el score de riesgo considerando:
    - Mantenimientos perdidos históricos
    - Diferencia con el mes anterior (CRÍTICO)
    - Tendencia general
    """
    score = 0
    
    # Puntos por mantenimientos perdidos históricos
    score += mantenimientos_perdidos.get(site, 0)
    
    # CRÍTICO: Puntos por disminución respecto al mes anterior
    if site in diferencias_mtto:
        dif = diferencias_mtto[site]["diferencia"]
        if dif < 0:
            # Penalización mayor si la caída es significativa
            score += abs(dif) * 2  # Multiplicador para dar más peso
    
    # Clasificación de riesgo
    if score >= 10:
        return "🔴 ALTO RIESGO", score
    elif score >= 5:
        return "🟡 MEDIO RIESGO", score
    else:
        return "🟢 BAJO RIESGO", score

def analizar_desempeno_contratistas(df, col_contratista, col_site, col_estado):
    """
    Analiza el desempeño de contratistas enfocado en estados de mantenimiento.
    Retorna métricas detalladas por contratista.
    """
    # Agrupar por contratista y estado
    desempeno = df.groupby([col_contratista, col_estado]).size().unstack(fill_value=0)
    
    # Calcular totales y porcentajes
    desempeno['TOTAL'] = desempeno.sum(axis=1)
    
    if 'Ejecutado' in desempeno.columns:
        desempeno['% Ejecutado'] = (desempeno['Ejecutado'] / desempeno['TOTAL'] * 100).round(1)
    else:
        desempeno['% Ejecutado'] = 0
        
    if 'Cancelado' in desempeno.columns:
        desempeno['% Cancelado'] = (desempeno['Cancelado'] / desempeno['TOTAL'] * 100).round(1)
    else:
        desempeno['% Cancelado'] = 0
        
    if 'Pendiente' in desempeno.columns:
        desempeno['% Pendiente'] = (desempeno['Pendiente'] / desempeno['TOTAL'] * 100).round(1)
    else:
        desempeno['% Pendiente'] = 0
    
    # Contar sitios únicos por contratista
    sitios_por_contratista = df.groupby(col_contratista)[col_site].nunique()
    desempeno['Sitios_Atendidos'] = sitios_por_contratista
    
    # Identificar contratistas problemáticos
    contratistas_problematicos = desempeno[
        (desempeno['% Cancelado'] > 15) | 
        (desempeno['% Ejecutado'] < 70)
    ].copy()
    
    # Ordenar columnas para mejor visualización
    columnas_orden = ['Sitios_Atendidos', 'TOTAL', 'Ejecutado', '% Ejecutado', 
                     'Pendiente', '% Pendiente', 'Cancelado', '% Cancelado']
    columnas_disponibles = [col for col in columnas_orden if col in desempeno.columns]
    
    return desempeno[columnas_disponibles], contratistas_problematicos

def detectar_especialidades_eliminadas(conteo_df, col_site, especialidades):
    """Detecta especialidades que han sido eliminadas permanentemente (3+ meses consecutivos de caída)"""
    eliminadas = {}
    mantenimientos_perdidos = {}
    
    for site in conteo_df[col_site].unique():
        site_data = conteo_df[conteo_df[col_site] == site].sort_values("MES")
        eliminadas[site] = []
        mantenimientos_perdidos[site] = 0
        
        for especialidad in especialidades:
            if especialidad not in site_data.columns:
                continue
                
            serie = site_data[especialidad].fillna(0).astype(int)
            
            if len(serie) < 3:
                continue
                
            # Detectar caídas consecutivas respecto al máximo histórico
            maximo_acumulado = serie.expanding().max()
            caidas = (serie < maximo_acumulado)
            
            contador_consecutivo = 0
            eliminado = False
            
            for hay_caida in caidas:
                if hay_caida:
                    contador_consecutivo += 1
                    if contador_consecutivo >= 3:
                        eliminado = True
                        break
                else:
                    contador_consecutivo = 0
            
            if eliminado:
                eliminadas[site].append(especialidad)
                max_historico = serie.max()
                valor_actual = serie.iloc[-1]
                mantenimientos_perdidos[site] += max_historico - valor_actual
    
    return eliminadas, mantenimientos_perdidos

def calcular_tendencias(conteo_df, col_site):
    """Calcula la tendencia mes a mes para cada sitio"""
    tendencias = {}
    
    for site in conteo_df[col_site].unique():
        site_data = conteo_df[conteo_df[col_site] == site].sort_values("MES")
        
        if len(site_data) < 2:
            continue
            
        mantenimiento_anterior = site_data.iloc[-2]["TOTAL"]
        mantenimiento_actual = site_data.iloc[-1]["TOTAL"]
        diferencia = mantenimiento_actual - mantenimiento_anterior
        
        if diferencia == 0:
            estado = "ESTABLE"
        elif diferencia < 0:
            estado = "DECRECIENDO"
        else:
            estado = "CRECIENDO"
        
        tendencias[site] = {
            "tendencia": estado,
            "valor": diferencia,
            "ultimo_mes": mantenimiento_actual
        }
    
    return tendencias

def diferencia_mtto_anterior(conteo_df, col_site):
    """
    Analiza la diferencia de mantenimientos con respecto al mes anterior.
    Esta función es VITAL para detectar caídas en la ejecución.
    Retorna un diccionario con la diferencia para cada sitio.
    """
    diferencias = {}
    
    for site in conteo_df[col_site].unique():
        site_data = conteo_df[conteo_df[col_site] == site].sort_values("MES")
        
        if len(site_data) < 2:
            diferencias[site] = {
                "diferencia": 0,
                "mes_actual": site_data.iloc[-1]["TOTAL"] if len(site_data) > 0 else 0,
                "mes_anterior": 0,
                "alerta": False
            }
            continue
        
        mes_anterior = site_data.iloc[-2]["TOTAL"]
        mes_actual = site_data.iloc[-1]["TOTAL"]
        diferencia = mes_actual - mes_anterior
        
        diferencias[site] = {
            "diferencia": diferencia,
            "mes_actual": mes_actual,
            "mes_anterior": mes_anterior,
            "alerta": diferencia < 0  # Alerta si hay disminución
        }
    
    return diferencias

def verificar_pendientes_no_ejecutados(df, col_site, col_especialidad, col_estado, col_mes):
    """
    Verifica si los mantenimientos marcados como 'Pendiente' fueron ejecutados
    en el SIGUIENTE mantenimiento programado (sin importar cuántos meses después).
    
    Busca el siguiente registro cronológico de la misma combinación sitio+especialidad
    y verifica si el pendiente fue resuelto.
    """
    alertas_pendientes = []
    
    # Normalizar estados a minúsculas
    df_temp = df.copy()
    df_temp[col_estado] = df_temp[col_estado].str.lower().str.strip()
    
    # Ordenar por sitio, especialidad y mes
    df_temp = df_temp.sort_values([col_site, col_especialidad, col_mes])
    
    # Filtrar solo pendientes
    df_pendientes = df_temp[df_temp[col_estado] == "pendiente"]
    
    for idx, row in df_pendientes.iterrows():
        sitio = row[col_site]
        especialidad = row[col_especialidad]
        mes_pendiente = row[col_mes]
        
        # Buscar TODOS los registros del mismo sitio+especialidad
        registros_misma_combinacion = df_temp[
            (df_temp[col_site] == sitio) &
            (df_temp[col_especialidad] == especialidad)
        ].sort_values(col_mes)
        
        # Encontrar el índice del registro pendiente actual
        indices_temporales = registros_misma_combinacion.index.tolist()
        
        if idx in indices_temporales:
            posicion_actual = indices_temporales.index(idx)
            
            # Verificar si hay un siguiente registro
            if posicion_actual < len(indices_temporales) - 1:
                # Obtener el SIGUIENTE registro cronológico
                siguiente_registro = registros_misma_combinacion.iloc[posicion_actual + 1]
                
                mes_siguiente = siguiente_registro[col_mes]
                estado_siguiente = siguiente_registro[col_estado]
                
                # Calcular diferencia de meses (aproximada)
                try:
                    # Extraer año y mes de formato "2023-01"
                    año_pend, mes_pend = mes_pendiente.split('-')
                    año_sig, mes_sig = mes_siguiente.split('-')
                    
                    meses_diferencia = (int(año_sig) - int(año_pend)) * 12 + (int(mes_sig) - int(mes_pend))
                    dias_aproximados = meses_diferencia * 30
                except:
                    meses_diferencia = 0
                    dias_aproximados = 0
                
                # VERIFICAR SI MESES_DIFERENCIA ES 0 - NO GENERAR ALERTA
                if meses_diferencia == 0:
                    continue  # Saltar a la siguiente iteración del bucle
                
                # Si NO está ejecutado en el siguiente mantenimiento, generar alerta
                if estado_siguiente != "ejecutado":
                    # Determinar severidad según estado y tiempo transcurrido
                    if estado_siguiente == "cancelado":
                        severidad = "MEDIA"
                    elif meses_diferencia >= 6:
                        severidad = "CRÍTICA"
                    elif meses_diferencia >= 3:
                        severidad = "ALTA"
                    else:
                        severidad = "MEDIA"
                    
                    alertas_pendientes.append({
                        "sitio": sitio,
                        "especialidad": especialidad,
                        "mes_pendiente": mes_pendiente,
                        "mes_siguiente_mtto": mes_siguiente,
                        "meses_entre_mttos": meses_diferencia,
                        "estado_siguiente": estado_siguiente.upper(),
                        "dias_sin_ejecutar": f"{dias_aproximados}+",
                        "severidad": severidad
                    })
    
    return alertas_pendientes
# === CARGA Y PROCESAMIENTO DE DATOS ===
if ARCHIVO:
    df = pd.read_excel(ARCHIVO, sheet_name=HOJA)
    df.columns = df.columns.str.strip()
    
    # Preparar columna de fecha
    df[COL_FECHA] = df[COL_FECHA].astype(str).str.strip().str.lower()
    df["MES"] = df[COL_FECHA].apply(convertir_mes_ano)
    
    # Filtrar por estado
    df_ejecutados = df[df[COL_ESTADO].str.lower() == "ejecutado"]
    df_cancelados = df[df[COL_ESTADO].str.lower() == "cancelado"]
    df_pendientes = df[df[COL_ESTADO].str.lower() == "pendiente"]
    
    # === CONTEO DE ESPECIALIDADES EJECUTADAS ===
    conteo_ejecutadas = (
        df_ejecutados.groupby([COL_SITE, "MES", COL_ESPECIALIDAD])
        .size()
        .unstack(fill_value=0)
    )
    
    for especialidad in ESPECIALIDADES:
        if especialidad not in conteo_ejecutadas.columns:
            conteo_ejecutadas[especialidad] = 0
    
    conteo_ejecutadas = conteo_ejecutadas[ESPECIALIDADES]
    conteo_ejecutadas["TOTAL"] = conteo_ejecutadas.sum(axis=1)
    conteo_ejecutadas.reset_index(inplace=True)
    
    # === ANÁLISIS ===
    eliminadas, mantenimientos_perdidos = detectar_especialidades_eliminadas(
        conteo_ejecutadas, COL_SITE, ESPECIALIDADES
    )
    diferencias_mtto = diferencia_mtto_anterior(conteo_ejecutadas, COL_SITE)
    tendencias = calcular_tendencias(conteo_ejecutadas, COL_SITE)
    desempeno_contratistas, contratistas_problematicos = analizar_desempeno_contratistas(
        df, COL_CONTRATISTA, COL_SITE, COL_ESTADO
    )
    
    # NUEVO: Verificar pendientes no ejecutados
    alertas_pendientes = verificar_pendientes_no_ejecutados(
        df, COL_SITE, COL_ESPECIALIDAD, COL_ESTADO, "MES"
    )
    
    # Calcular riesgos
    prioridad_df = df[[COL_SITE, COL_PRIORIDAD]].drop_duplicates()
    riesgos = {}
    scores = {}
    for site in df[COL_SITE].unique():
        riesgo, score = calcular_score_riesgo(
            site, eliminadas, mantenimientos_perdidos, diferencias_mtto, prioridad_df
        )
        riesgos[site] = riesgo
        scores[site] = score
    
    # === MÉTRICAS GLOBALES (SIDEBAR) ===
    st.header("📈 Métricas Globales")
    total_sitios = df[COL_SITE].nunique()
    tasa_ejecucion = (len(df_ejecutados) / len(df) * 100) if len(df) > 0 else 0
    sitios_con_problemas = len([s for s, elims in eliminadas.items() if elims])

    col_m1, col_m2, col_m3, col_m4 = st.columns(4)

    with col_m1:
        st.metric("🏢 Total Sitios", total_sitios)
    with col_m2:
        st.metric("✅ Tasa Ejecución", f"{tasa_ejecucion:.1f}%")

    with col_m3:
        st.metric("🚨 Sitios con Problemas", sitios_con_problemas)

    with col_m4:
        if alertas_pendientes:
            st.metric("⏰ Pendientes sin Ejecutar", len(alertas_pendientes), 
                            delta=f"-{len(alertas_pendientes)}", delta_color="inverse")
    
    # === REPORTE EJECUTIVO ===
    st.header("Reporte General")

    st.subheader("📈 Tendencias en los sitios")
    sitios_decreciendo = [s for s, t in tendencias.items() if "DECRECIENDO" in t["tendencia"]]
    sitios_creciendo = [s for s, t in tendencias.items() if "CRECIENDO" in t["tendencia"]]
    sitios_estables = [s for s, t in tendencias.items() if "ESTABLE" in t["tendencia"]]

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("↘️ Menos mantenimientos en:", len(sitios_decreciendo))
    with col2:
        st.metric("↗️ Más mantenimientos en:", len(sitios_creciendo))
    with col3: 
        st.metric("➡️ Los mismos mantenimientos en:", len(sitios_estables))
    
    
    # === NUEVA SECCIÓN: ALERTAS DE PENDIENTES NO EJECUTADOS ===
    if alertas_pendientes:
        st.markdown("---")
        st.header("Seguimiento de mantenimientos Pendientes")
        
        # Contador por severidad
        criticos = len([a for a in alertas_pendientes if a['severidad'] == 'CRÍTICA'])
        altos = len([a for a in alertas_pendientes if a['severidad'] == 'ALTA'])
        medios = len([a for a in alertas_pendientes if a['severidad'] == 'MEDIA'])
        
        col_alert1, col_alert2, col_alert3, col_alert4 = st.columns(4)
        
        with col_alert1:
            st.metric("🔴 Críticos", criticos)
        with col_alert2:
            st.metric("🟠 Altos", altos)
        with col_alert3:
            st.metric("🟡 Medios", medios)
        with col_alert4:
            st.metric("📊 Total", len(alertas_pendientes))
        
        # Mostrar tabla de alertas
        st.subheader("Detalle de Pendientes No Ejecutados")
        
        df_alertas = pd.DataFrame(alertas_pendientes)
        
        # Aplicar colores según severidad
        def colorear_severidad(val):
            if val == 'CRÍTICA':
                return 'background-color: #fee2e2; color: #991b1b; font-weight: bold'
            elif val == 'ALTA':
                return 'background-color: #fed7aa; color: #9a3412; font-weight: bold'
            elif val == 'MEDIA':
                return 'background-color: #fef3c7; color: #92400e; font-weight: bold'
            return ''
        
        st.dataframe(
            df_alertas.style.applymap(colorear_severidad, subset=['severidad']),
            width='stretch'
        )
        
        
    else:
        st.success("✅ No hay mantenimientos pendientes sin ejecutar")
    
    # === ANÁLISIS DE CONTRATISTAS (MEJORADO) ===
    st.header("👷 Análisis Detallado de los FLM")

    # Mostrar todos los contratistas con detalles expandibles
    st.subheader("Desempeño General")
    st.dataframe(
        desempeno_contratistas.style.background_gradient(
            subset=['% Ejecutado'], cmap='RdYlGn', vmin=0, vmax=100
        ).background_gradient(
            subset=['% Cancelado'], cmap='RdYlGn_r', vmin=0, vmax=100
        ),
        width='content'
    )

    # Detalle expandible para CADA contratista (no solo los problemáticos)
    st.subheader("Detalle por FLM")
    for contratista in desempeno_contratistas.index:
        st.subheader(f"{contratista} - {desempeno_contratistas.loc[contratista, '% Ejecutado']:.1f}% Ejecutado")
        # Obtener sitios de este contratista
        sitios_contratista = df[df[COL_CONTRATISTA] == contratista][COL_SITE].unique()
        
        # Desglose por estado
        col_a, col_b, col_c = st.columns(3)
        datos = desempeno_contratistas.loc[contratista]
        
        with col_a:
            st.metric("Ejecutado", f"{datos.get('Ejecutado', 0):.0f}", 
                    f"{datos.get('% Ejecutado', 0):.1f}%")
        with col_b:
            st.metric("Pendiente", f"{datos.get('Pendiente', 0):.0f}", 
                    f"{datos.get('% Pendiente', 0):.1f}%")
        with col_c:
            st.metric("Cancelado", f"{datos.get('Cancelado', 0):.0f}", 
                    f"{datos.get('% Cancelado', 0):.1f}%", delta_color="inverse")

    
    st.markdown("---")
    
    # === ANÁLISIS POR PRIORIDAD ===
    st.header("Análisis por Prioridad de Sitio")
    
    grupos_prioridades = {
        "P1": "P_1", "P2": "P_2", "P3": "P_3",
        "D1": "D_1", "D2": "D_2", "D3": "D_3",
        "B1": "B_1", "B2": "B_2", "B3": "B_3"
    }
    
    tabs = st.tabs([f"Sites {k}" for k in grupos_prioridades.keys()])
    
    for (nombre_tab, codigo_prioridad), tab in zip(grupos_prioridades.items(), tabs):
        with tab:
            # Filtrar sitios de esta prioridad
            sitios_prioridad = prioridad_df[prioridad_df[COL_PRIORIDAD] == codigo_prioridad][COL_SITE].unique()
            
            # Sitios con problemas en esta prioridad (problemas de eliminacion de especialidades y de menos mttos este mes )
            sitios_con_alerta = [s for s in sitios_prioridad 
                                if (s in eliminadas and eliminadas[s]) or 
                                (s in tendencias and "DECRECIENDO" in tendencias[s]["tendencia"])]
            
            if sitios_con_alerta:
                st.write(f"**⚠️ {len(sitios_con_alerta)} sitios con alertas en {nombre_tab}**")
                
                for site in sitios_con_alerta:
                    site_data = conteo_ejecutadas[conteo_ejecutadas[COL_SITE] == site].sort_values("MES")
                    riesgo_sitio = riesgos.get(site, "🟢 BAJO RIESGO")
                    total_perdidos = mantenimientos_perdidos.get(site, 0)
                    
                    # Determinar el tipo de problema para el título
                    tiene_eliminadas = site in eliminadas and eliminadas[site]
                    esta_decreciendo = site in tendencias and "DECRECIENDO" in tendencias[site]["tendencia"]
                    
                    titulo_problema = ""
                    if tiene_eliminadas and esta_decreciendo:
                        titulo_problema = f"{total_perdidos} especialidades eliminadas y menos mantenimientos realizados este mes"
                    elif tiene_eliminadas:
                        titulo_problema = f"{total_perdidos} especialidades eliminadas"
                    elif esta_decreciendo:
                        titulo_problema = "Menos mantenimientos realizados este mes"
                    
                    with st.expander(f"{riesgo_sitio} | {site} — {titulo_problema}"):
                        # Información de tendencia
                        if site in tendencias:
                            tend = tendencias[site]
                            st.metric("Tendencia", tend["tendencia"], f"{tend['valor']:+d} mttos")
                        
                        # Especialidades eliminadas (si aplica)
                        if tiene_eliminadas:
                            st.write("**🔴 Especialidades eliminadas:**")
                            for esp in eliminadas[site]:
                                serie_esp = site_data[esp].fillna(0).astype(int)
                                max_hist = serie_esp.max()
                                actual = serie_esp.iloc[-1] if len(serie_esp) > 0 else 0
                                perdidos = max_hist - actual
                                st.write(f"- **{esp}**: {perdidos} eliminados (máx: {max_hist}, actual: {actual})")
                        
                        # Gráfico de evolución
                        columnas_grafico = [c for c in site_data.columns 
                                        if c not in [COL_SITE, "MES", "TOTAL"]]
                        df_grafico = site_data.melt(
                            id_vars=["MES"],
                            value_vars=columnas_grafico,
                            var_name="Especialidad",
                            value_name="Cantidad"
                        )
                        st.bar_chart(df_grafico, x="MES", y="Cantidad", color="Especialidad", horizontal=True)
    
    # === DESCARGA DE REPORTE ===
    st.markdown("---")
    st.header("📥 Descarga de Reporte")
    
    with pd.ExcelWriter("Reporte_Mantenimientos.xlsx") as writer:
        desempeno_contratistas.to_excel(writer, sheet_name="Desempeño_Contratistas")
        contratistas_problematicos.to_excel(writer, sheet_name="Contratistas_Problemáticos")
        
        # Hoja de riesgos
        df_riesgos = pd.DataFrame([
            {
                "Sitio": site,
                "Riesgo": riesgo,
                "Score": scores[site],
                "Especialidades_Eliminadas": len(eliminadas.get(site, [])),
                "Mttos_Perdidos": mantenimientos_perdidos.get(site, 0)
            }
            for site, riesgo in riesgos.items()
        ]).sort_values("Score", ascending=False)
        df_riesgos.to_excel(writer, sheet_name="Análisis_Riesgo", index=False)
    
    with open("Reporte_Mantenimientos.xlsx", "rb") as file:
        st.download_button(
            label="⬇️ Descargar Reporte Completo en Excel",
            data=file,
            file_name=f"Reporte_Mantenimientos_{datetime.now().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

else:
    st.info("📂 Por favor carga un archivo Excel para iniciar el análisis.")