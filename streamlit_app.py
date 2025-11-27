# === Importación de librerías ===
import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime
from pathlib import Path


# === CONFIGURACIÓN INICIAL ===
st.set_page_config(page_title="Control de Mantenimientos", layout="wide")

# agregar la ruta del archivo donde esten los preventivos
# === CONSTANTES ===
ARCHIVO = Path("C:/Users/lcadillom/OneDrive - Integratel Perú/1_Compartido_KPI/1.- Reporte de Mtto Preventivo/V6.Autin -Segu mtto Preventivo (26_ Noviembre 09;19).xlsx")
HOJA = "Data"

# Nombres de columnas
COL_ESPECIALIDAD = "SUB_ESPECIALIDAD"
COL_SITE_ID = "Site Id"
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
        return "ALTO RIESGO", score
    elif score >= 5:
        return "MEDIO RIESGO", score
    else:
        return "BAJO RIESGO", score

def analizar_desempeno_contratistas(df, col_contratista, col_site_id, col_estado):
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
    sitios_por_contratista = df.groupby(col_contratista)[col_site_id].nunique()
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

def detectar_especialidades_eliminadas(conteo_df,col_site_id,  especialidades):
    """Detecta especialidades que han sido eliminadas permanentemente (3+ meses consecutivos de caída)"""
    eliminadas = {}
    mantenimientos_perdidos = {}
    
    for site in conteo_df[col_site_id].unique():
        site_data = conteo_df[conteo_df[col_site_id] == site].sort_values("MES")
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

def calcular_tendencias(conteo_df, col_site_id):
    """Calcula la tendencia mes a mes para cada sitio basado en el 80% del promedio histórico"""
    tendencias = {}
    
    for site in conteo_df[col_site_id].unique():
        site_data = conteo_df[conteo_df[col_site_id] == site].sort_values("MES")
        
        if len(site_data) < 2:
            continue
            
        # Calcular el promedio histórico (excluyendo el último mes)
        mantenimientos_historicos = site_data.iloc[:-1]["TOTAL"]
        promedio_historico = mantenimientos_historicos.mean()
        
        # Umbral del 80% del promedio histórico
        umbral_80_porciento = promedio_historico * 0.8
        
        mantenimiento_actual = site_data.iloc[-1]["TOTAL"]
        mantenimiento_anterior = site_data.iloc[-2]["TOTAL"]
        diferencia = mantenimiento_actual - mantenimiento_anterior
        
        # Verificar si hay 3 meses consecutivos sin variación
        tiene_3_meses_estables = False
        if len(site_data) >= 3:
            ultimos_3_meses = site_data.tail(3)["TOTAL"].values
            # Verificar si los últimos 3 meses tienen el mismo valor
            if len(set(ultimos_3_meses)) == 1:  # Todos los valores son iguales
                tiene_3_meses_estables = True
        
        # Determinar tendencia
        if tiene_3_meses_estables:
            estado = "ESTABLE"
        elif mantenimiento_actual >= promedio_historico:
            estado = "CRECIENDO"
        elif mantenimiento_actual >= umbral_80_porciento:
            estado = "ESTABLE"
        else:
            estado = "DECRECIENDO"
        
        tendencias[site] = {
            "tendencia": estado,
            "valor": diferencia,
            "ultimo_mes": mantenimiento_actual,
            "promedio_historico": round(promedio_historico, 1),
            "umbral_80p": round(umbral_80_porciento, 1),
            "3_meses_estables": tiene_3_meses_estables
        }
    
    return tendencias

def diferencia_mtto_anterior(conteo_df, col_site_id):
    """
    Analiza la diferencia de mantenimientos con respecto al mes anterior.
    Esta función es VITAL para detectar caídas en la ejecución.
    Retorna un diccionario con la diferencia para cada sitio.
    """
    diferencias = {}
    
    for site in conteo_df[col_site_id].unique():
        site_data = conteo_df[conteo_df[col_site_id] == site].sort_values("MES")
        
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

def verificar_pendientes_no_ejecutados(df, col_site_id, col_site, col_especialidad, col_estado, col_mes):
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
    df_temp = df_temp.sort_values([col_site_id, col_site, col_especialidad, col_mes])
    
    # Filtrar solo pendientes
    df_pendientes = df_temp[df_temp[col_estado] == "pendiente"]
    
    for idx, row in df_pendientes.iterrows():
        sitio_id = row[col_site_id]
        sitio_name = row[col_site]
        especialidad = row[col_especialidad]
        mes_pendiente = row[col_mes]
        
        # Mantenimientos programados de esta especialidad en el mes pendiente
        mttos_programados_mes_pendiente = len(df_temp[
            (df_temp[col_site_id] == sitio_id) &
            (df_temp[col_site] == sitio_name) &
            (df_temp[col_especialidad] == especialidad) &  # ← FILTRAR POR ESPECIALIDAD
            (df_temp["MES"] == mes_pendiente)
        ])
        
        # Mantenimientos ejecutados de esta especialidad en el mes pendiente
        mttos_recuento_ejecutados = len(df_temp[
            (df_temp[col_site_id] == sitio_id) &
            (df_temp[col_site] == sitio_name) &
            (df_temp[col_especialidad] == especialidad) &  # ← FILTRAR POR ESPECIALIDAD
            (df_temp["MES"] == mes_pendiente) &
            (df_temp[col_estado] == "ejecutado")
        ])
        
        # Buscar TODOS los registros del mismo sitio+especialidad
        registros_misma_combinacion = df_temp[
            (df_temp[col_site_id] == sitio_id) &
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
                
                # === MODIFICADO: Contar mantenimientos de LA MISMA SUBESPECIALIDAD para el mes siguiente ===
                mttos_programados_mes_siguiente = len(df_temp[
                    (df_temp[col_site_id] == sitio_id) &
                    (df_temp[col_site] == sitio_name) &
                    (df_temp[col_especialidad] == especialidad) &  # ← FILTRAR POR ESPECIALIDAD
                    (df_temp["MES"] == mes_siguiente)
                ])
                
                mttos_recuento_ejecutados2 = len(df_temp[
                    (df_temp[col_site_id] == sitio_id) &
                    (df_temp[col_site] == sitio_name) &
                    (df_temp[col_especialidad] == especialidad) &  # ← FILTRAR POR ESPECIALIDAD
                    (df_temp["MES"] == mes_siguiente) &
                    (df_temp[col_estado] == "ejecutado")
                ])
                
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
                        "site ID": sitio_id,
                        "site": sitio_name,
                        "especialidad": especialidad,
                        "mes_pendiente": mes_pendiente,
                        "mes_siguiente_mtto": mes_siguiente,
                        "meses_entre_mttos": meses_diferencia,
                        "estado_siguiente": estado_siguiente.upper(),
                        "dias_sin_ejecutar": f"{dias_aproximados}+",
                        "severidad": severidad,
                        # === NUEVAS COLUMNAS AGREGADAS ===
                        "recuento_ejecutados": f"{mttos_recuento_ejecutados}/{mttos_programados_mes_pendiente}",
                        "recuento_ejecutados2": f"{mttos_recuento_ejecutados2}/{mttos_programados_mes_siguiente}"
                    })
    
    return alertas_pendientes

# === CARGA Y PROCESAMIENTO DE DATOS (se ejecuta una sola vez) ===
@st.cache_data
def cargar_datos():
    """Carga y procesa los datos una sola vez"""
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
            df_ejecutados.groupby([COL_SITE_ID, "MES", COL_ESPECIALIDAD])
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
            conteo_ejecutadas, COL_SITE_ID, ESPECIALIDADES
        )
        diferencias_mtto = diferencia_mtto_anterior(conteo_ejecutadas, COL_SITE_ID)
        tendencias = calcular_tendencias(conteo_ejecutadas, COL_SITE_ID)
        desempeno_contratistas, contratistas_problematicos = analizar_desempeno_contratistas(
            df, COL_CONTRATISTA, COL_SITE_ID, COL_ESTADO
        )
        
        # Verificar pendientes no ejecutados
        alertas_pendientes = verificar_pendientes_no_ejecutados(
            df, COL_SITE_ID, COL_SITE, COL_ESPECIALIDAD, COL_ESTADO, "MES"
        )
        
        # Calcular riesgos
        prioridad_df = df[[COL_SITE_ID, COL_SITE, COL_PRIORIDAD]].drop_duplicates()
        riesgos = {}
        scores = {}
        for site in df[COL_SITE_ID].unique():
            riesgo, score = calcular_score_riesgo(
                site, eliminadas, mantenimientos_perdidos, diferencias_mtto, prioridad_df
            )
            riesgos[site] = riesgo
            scores[site] = score
        
        return {
            'df': df,
            'df_ejecutados': df_ejecutados,
            'df_cancelados': df_cancelados,
            'df_pendientes': df_pendientes,
            'conteo_ejecutadas': conteo_ejecutadas,
            'eliminadas': eliminadas,
            'mantenimientos_perdidos': mantenimientos_perdidos,
            'diferencias_mtto': diferencias_mtto,
            'tendencias': tendencias,
            'desempeno_contratistas': desempeno_contratistas,
            'contratistas_problematicos': contratistas_problematicos,
            'alertas_pendientes': alertas_pendientes,
            'prioridad_df': prioridad_df,
            'riesgos': riesgos,
            'scores': scores
        }
    else:
        return None
    
# === PÁGINA DE BIENVENIDA ===
def pagina_bienvenida():
    # Header principal con estilo
    st.markdown("""
    <div style="text-align: center; padding: 2rem 0;">
        <h1 style="font-size: 3rem; margin-bottom: 0.5rem;">Control de Ejecución de especialidades en Mantenimientos Preventivos</h1>
        <p style="font-size: 1.3rem; color: #666;"></p>
    </div>
    """, unsafe_allow_html=True)
    
    datos = st.session_state.datos
    
    if datos is None:
        st.error("No se pudieron cargar los datos. Verifica que el archivo Excel esté disponible.")
        return
    
    # Sección de botones de navegación principal
    
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("**Búsqueda por Site ID**", 
                     width="stretch",  type="primary", icon=":material/search:"):
            st.session_state.pagina_actual = "Búsqueda por Site ID"
            st.rerun()
        
        if st.button("**Sitios Problemáticos**", 
                     width="stretch",  type="primary", icon=":material/error:"):
            st.session_state.pagina_actual = "Sitios Problemáticos"
            st.rerun()
        
        if st.button("**Análisis por Especialidades**", 
                     width="stretch", type="primary", icon=":material/finance_mode:"):
            st.session_state.pagina_actual = "Especialidades"
            st.rerun()
    
    with col2:
        if st.button("**Mantenimientos Pendientes**", 
                     width="stretch",  type="primary", icon=":material/pending_actions:"):
            st.session_state.pagina_actual = "Mantenimientos Pendientes"
            st.rerun()
        
        if st.button("**Desempeño de los FLM** ", 
                     width="stretch",  type="primary", icon=":material/engineering:"):
            st.session_state.pagina_actual = "Análisis FLM"
            st.rerun()
    
    
    # Footer
    st.markdown("---")
    col_foot1, col_foot2, col_foot3 = st.columns(3)
    
    with col_foot1:
        st.caption(f"{len(datos['df'])} registros totales")
    
    with col_foot2:
        meses_disponibles = datos['df']['MES'].nunique()
        st.caption(f" {meses_disponibles} meses de historial")
    
    with col_foot3:
        st.caption(f" Versión 1.0")

    
# === PÁGINA DE BÚSQUEDA POR SITE ID ===
def pagina_busqueda_site():
    st.title("Búsqueda por Site ID")
    
    datos = st.session_state.datos
    
    if datos is None:
        st.info(" Por favor carga un archivo Excel para iniciar el análisis.")
        return
    
    # Obtener lista de todos los Site IDs disponibles
    lista_sites = sorted(datos['df'][COL_SITE_ID].unique())
    
    # Buscador con autocompletado
    site_buscado = st.selectbox(
        "Ingresar el ID del sitio buscado:",
        options=[""] + lista_sites,
        format_func=lambda x: "Escribe para buscar ... " if x == "" else x
    )
    
    if site_buscado and site_buscado != "":
        # Obtener información del sitio
        site_info = datos['prioridad_df'][datos['prioridad_df'][COL_SITE_ID] == site_buscado]
        
        if site_info.empty:
            st.error(f"No se encontró información para el Site ID: {site_buscado}")
            return
        
        site_name = site_info[COL_SITE].iloc[0]
        site_prioridad = site_info[COL_PRIORIDAD].iloc[0]
        
        # Filtrar datos del sitio
        df_site = datos['df'][datos['df'][COL_SITE_ID] == site_buscado]
        df_site_ejecutados = datos['df_ejecutados'][datos['df_ejecutados'][COL_SITE_ID] == site_buscado]
        df_site_pendientes = datos['df_pendientes'][datos['df_pendientes'][COL_SITE_ID] == site_buscado]
        df_site_cancelados = datos['df_cancelados'][datos['df_cancelados'][COL_SITE_ID] == site_buscado]
        
        contratista_site = df_site[COL_CONTRATISTA].iloc[0] if not df_site.empty else "No disponible"
        
        # Encabezado con información básica
        st.header(f"{site_buscado} — {site_name}  — {site_prioridad} ")
        st.subheader(f"FLM: {contratista_site} ")
        
        # === MÉTRICAS PRINCIPALES ===
        st.markdown("---")
        st.subheader("Resumen del sitio")
        
        col1, col2, col3, col4 = st.columns(4)
        
        total_mttos = len(df_site)
        ejecutados = len(df_site_ejecutados)
        pendientes = len(df_site_pendientes)
        cancelados = len(df_site_cancelados)
        
        with col1:
            st.metric("Total Mantenimientos", total_mttos, border=True)
        with col2:
            porcentaje = (ejecutados / total_mttos * 100) if total_mttos > 0 else 0
            st.metric("Ejecutados", ejecutados, f"{porcentaje:.1f}%", border=True)
        with col3:
            porcentaje = (pendientes / total_mttos * 100) if total_mttos > 0 else 0
            st.metric("Pendientes", pendientes, f"{porcentaje:.1f}%", border=True)
        with col4:
            porcentaje = (cancelados / total_mttos * 100) if total_mttos > 0 else 0
            st.metric("Cancelados", cancelados, f"{porcentaje:.1f}%", delta_color="inverse", border=True)
     
        
    
        # === ANÁLISIS DE RIESGO ===
        riesgo_sitio = datos['riesgos'].get(site_buscado, "BAJO RIESGO")
        score_riesgo = datos['scores'].get(site_buscado, 0)
        
        if score_riesgo >= 10:
            st.markdown("---")
            st.subheader("Evaluación de Riesgo")
            
            
            
            if "ALTO" in riesgo_sitio:
                st.error(f"**{riesgo_sitio}**")
            elif "MEDIO" in riesgo_sitio:
                st.warning(f"**{riesgo_sitio}**")
            else:
                st.success(f"**{riesgo_sitio}**")
        
        # === TENDENCIA ===
        
        
        if site_buscado in datos['tendencias']:
            st.markdown("---")
            st.subheader("Análisis de Tendencia")
            tend = datos['tendencias'][site_buscado]
            
            col_t2, col_t3, col_t4 = st.columns(3)
            
            with col_t2:
                st.metric("Variación vs Mes Anterior", 
                         f"{tend['valor']:+d} mttos", 
                         border=True)
            
            with col_t3:
                st.metric("Mantenimientos Actuales", 
                         tend['ultimo_mes'], 
                         border=True)
            
            with col_t4:
                st.metric("Promedio Histórico", 
                         f"{tend['promedio_historico']:.1f}", 
                         border=True)
        
        # === ESPECIALIDADES ELIMINADAS ===
        if site_buscado in datos['eliminadas'] and datos['eliminadas'][site_buscado]:
            st.markdown("---")
            st.subheader("Especialidades Eliminadas")
            
            total_perdidos = datos['mantenimientos_perdidos'].get(site_buscado, 0)
            st.warning(f"**{total_perdidos} mantenimientos perdidos por eliminación de especialidades**")
            
            site_data = datos['conteo_ejecutadas'][datos['conteo_ejecutadas'][COL_SITE_ID] == site_buscado].sort_values("MES")
            
            for esp in datos['eliminadas'][site_buscado]:
                serie_esp = site_data[esp].fillna(0).astype(int)
                max_hist = serie_esp.max()
                actual = serie_esp.iloc[-1] if len(serie_esp) > 0 else 0
                perdidos = max_hist - actual
                
                st.write(f"- **{esp}**: {perdidos} mantenimientos eliminados (máx: {max_hist}, actual: {actual})")
        
        # === EVOLUCIÓN HISTÓRICA ===
        st.markdown("---")
        st.subheader("📊 Evolución Histórica de Mantenimientos")
        
        site_data = datos['conteo_ejecutadas'][datos['conteo_ejecutadas'][COL_SITE_ID] == site_buscado].sort_values("MES")
        
        if not site_data.empty:
            # Gráfico de evolución por especialidad
            columnas_grafico = [c for c in site_data.columns 
                              if c not in [COL_SITE_ID, COL_SITE, "MES", "TOTAL"]]
            
            df_grafico = site_data.melt(
                id_vars=["MES"],
                value_vars=columnas_grafico,
                var_name="Especialidad",
                value_name="Cantidad"
            )
            
            st.bar_chart(df_grafico, x="MES", y="Cantidad", color="Especialidad", horizontal=True)
            
            # Mostrar tabla de datos
            with st.expander("Ver como tabla"):
                columnas_mostrar = ["MES"] + columnas_grafico + ["TOTAL"]
                st.dataframe(site_data[columnas_mostrar], hide_index=True)
        else:
            st.info("No hay datos históricos disponibles para este sitio")
        
        
        # === ALERTAS DE PENDIENTES ===
        alertas_site = [a for a in datos['alertas_pendientes'] if a['site ID'] == site_buscado]
        
        if alertas_site:
            st.markdown("---")
            st.subheader("⚠️ Mantenimientos Pendientes sin Ejecutar")
            st.error(f"Este sitio tiene **{len(alertas_site)}** mantenimientos pendientes sin resolver")
            
            df_alertas_site = pd.DataFrame(alertas_site)
            
            # Aplicar estilos
            def aplicar_estilos_alertas(df):
                styles = pd.DataFrame('', index=df.index, columns=df.columns)
                if 'severidad' in df.columns:
                    styles['severidad'] = df['severidad'].apply(
                        lambda x: 'background-color: #fee2e2; color: #991b1b; font-weight: bold' if x == 'CRÍTICA' 
                        else 'background-color: #fed7aa; color: #9a3412; font-weight: bold' if x == 'ALTA'
                        else 'background-color: #fef3c7; color: #92400e; font-weight: bold'
                    )
                return styles
            
            styled_alertas = df_alertas_site.style.apply(aplicar_estilos_alertas, axis=None)
            st.dataframe(styled_alertas, hide_index=True) 

# === PÁGINA DE MANTENIMIENTOS PENDIENTES ===
def pagina_pendientes():
    st.title("Seguimiento de los mantenimientos pendientes")
    
    datos = st.session_state.datos
    
    if datos is None:
        st.info(" Por favor carga un archivo Excel para iniciar el análisis.")
        return

    # === ALERTAS DE PENDIENTES NO EJECUTADOS ===
    if datos['alertas_pendientes']:
        
        # Mostrar tabla de alertas
        st.subheader("Detalle de Pendientes No Ejecutados")
        
        df_alertas = pd.DataFrame(datos['alertas_pendientes'])
        
        # VERIFICAR SI LAS COLUMNAS NUEVAS EXISTEN, SI NO, CREARLAS CON VALORES POR DEFECTO
        if 'recuento_ejecutados' not in df_alertas.columns:
            df_alertas['recuento_ejecutados'] = 'N/A'
        if 'recuento_ejecutados2' not in df_alertas.columns:
            df_alertas['recuento_ejecutados2'] = 'N/A'
        
        # Reordenar columnas para mejor visualización
        column_order = [
            "site ID", "site", "especialidad", 
            "mes_pendiente", "recuento_ejecutados",
            "mes_siguiente_mtto", "recuento_ejecutados2",
            "meses_entre_mttos", "estado_siguiente", 
            "dias_sin_ejecutar", "severidad"
        ]
        
        # Filtrar solo las columnas que existen en el DataFrame
        columnas_disponibles = [col for col in column_order if col in df_alertas.columns]
        
        # Función para aplicar estilos
        def aplicar_estilos(df):
            """
            Aplica estilos de colores al DataFrame completo
            """
            styles = pd.DataFrame('', index=df.index, columns=df.columns)
            
            # Colorear columna 'severidad'
            if 'severidad' in df.columns:
                styles['severidad'] = df['severidad'].apply(
                    lambda x: 'background-color: #fee2e2; color: #991b1b; font-weight: bold' if x == 'CRÍTICA' 
                    else 'background-color: #fed7aa; color: #9a3412; font-weight: bold' if x == 'ALTA'
                    else 'background-color: #fef3c7; color: #92400e; font-weight: bold' if x == 'MEDIA'
                    else ''
                )
            
            # Colorear las nuevas columnas de azul
            if 'recuento_ejecutados' in df.columns:
                styles['recuento_ejecutados'] = 'background-color: #e6f3ff; color: #0066cc; font-weight: bold'
            
            if 'recuento_ejecutados2' in df.columns:
                styles['recuento_ejecutados2'] = 'background-color: #e6f3ff; color: #0066cc; font-weight: bold'
            
            return styles
        
        # Aplicar estilos
        styled_df = df_alertas[columnas_disponibles].style.apply(
            aplicar_estilos, 
            axis=None
        )
        
        st.dataframe(styled_df, width='stretch', hide_index=True)
        
        
    else:
        st.success("   No hay mantenimientos pendientes sin ejecutar")

# === PÁGINA DE ANÁLISIS DE FLM ===
def pagina_analisis_flm():
    st.title("Análisis de desempeño de los FLM")
    
    datos = st.session_state.datos
    
    if datos is None:
        st.info(" Por favor carga un archivo Excel para iniciar el análisis.")
        return
    
    # Mostrar todos los contratistas con detalles expandibles
    st.subheader("Desempeño General")
    st.dataframe(
        datos['desempeno_contratistas'].style.background_gradient(
            subset=['% Ejecutado'], cmap='RdYlGn', vmin=0, vmax=100
        ).background_gradient(
            subset=['% Cancelado'], cmap='RdYlGn_r', vmin=0, vmax=100
        ),
        width='content'
    )

    # Detalle expandible para CADA contratista (no solo los problemáticos)
    st.subheader("Detalle por FLM")
    for contratista in datos['desempeno_contratistas'].index:
        st.subheader(f"{contratista}")
        # Obtener sitios de este contratista
        sitios_contratista = datos['df'][datos['df'][COL_CONTRATISTA] == contratista][COL_SITE].unique()
        
        # Desglose por estado
        col_a, col_b, col_c = st.columns(3)
        datos_contratista = datos['desempeno_contratistas'].loc[contratista]
        
        with col_a:
            st.metric("Ejecutado", f"{datos_contratista.get('Ejecutado', 0):.0f}", 
                    f"{datos_contratista.get('% Ejecutado', 0):.1f}%", border=True)
        with col_b:
            st.metric("Pendiente", f"{datos_contratista.get('Pendiente', 0):.0f}", 
                    f"{datos_contratista.get('% Pendiente', 0):.1f}%", border=True)
        with col_c:
            st.metric("Cancelado", f"{datos_contratista.get('Cancelado', 0):.0f}", 
                    f"{datos_contratista.get('% Cancelado', 0):.1f}%", delta_color="inverse", border=True)

def pagina_sitios_problematicos():
    st.title("Sitios Problemáticos")
    
    datos = st.session_state.datos
    
    if datos is None:
        st.info(" Por favor carga un archivo Excel para iniciar el análisis.")
        return
    
    col_btn1, col_btn2 = st.columns(2)
    
    with col_btn1:
        if st.button("Especialidades Eliminadas", width="stretch", type="primary"):
            st.session_state.tipo_problema = "eliminadas"
    
    with col_btn2:
        if st.button("Menos Mantenimientos vs Mes Anterior", width="stretch" , type="primary"):
            st.session_state.tipo_problema = "decreciendo"
    
    # Inicializar tipo de problema si no existe
    if 'tipo_problema' not in st.session_state:
        st.session_state.tipo_problema = " "
    
    # === MOSTRAR SEGÚN TIPO DE PROBLEMA SELECCIONADO ===
    tipo_seleccionado = st.session_state.tipo_problema
    
    if tipo_seleccionado == "eliminadas":
        mostrar_sitios_con_especialidades_eliminadas(datos)
    else:
        mostrar_sitios_con_menos_mantenimientos(datos)


def mostrar_sitios_con_especialidades_eliminadas(datos):
    """Muestra sitios que tienen especialidades eliminadas (3+ meses consecutivos sin hacerse)"""
    
    st.header("Sitios con Especialidades Eliminadas")
    st.caption("Se consideran eliminadas las especialidades que no se ejecutaron durante 3 o más meses consecutivos respecto a su máximo histórico")

    grupos_prioridades = {
        "P1": "P_1", "P2": "P_2", "P3": "P_3",
        "D1": "D_1", "D2": "D_2", "D3": "D_3",
        "B1": "B_1", "B2": "B_2", "B3": "B_3"
    }
    
    tabs = st.tabs([f"Sites {k}" for k in grupos_prioridades.keys()])
    
    for (nombre_tab, codigo_prioridad), tab in zip(grupos_prioridades.items(), tabs):
        with tab:
            # Filtrar sitios de esta prioridad
            sitios_prioridad = datos['prioridad_df'][
                datos['prioridad_df'][COL_PRIORIDAD] == codigo_prioridad
            ][COL_SITE_ID].unique()
            
            # Sitios con especialidades eliminadas en esta prioridad
            sitios_con_alerta = [
                s for s in sitios_prioridad 
                if s in datos['eliminadas'] and datos['eliminadas'][s]
            ]
            
            if sitios_con_alerta:
                st.write(f"**⚠️ {len(sitios_con_alerta)} sitios con especialidades eliminadas en {nombre_tab}**")
                
                # Agrupar sitios por nivel de riesgo
                sitios_por_riesgo = {
                    "ALTO RIESGO": [],
                    "MEDIO RIESGO": [],
                    "BAJO RIESGO": []
                }
                
                for site in sitios_con_alerta:
                    riesgo_sitio = datos['riesgos'].get(site, "BAJO RIESGO")
                    sitios_por_riesgo[riesgo_sitio].append(site)
                
                # Mostrar por grupos de riesgo
                for nivel_riesgo in ["ALTO RIESGO", "MEDIO RIESGO", "BAJO RIESGO"]:
                    sitios_nivel = sitios_por_riesgo[nivel_riesgo]
                    
                    if sitios_nivel:
                        # Determinar color del badge
                        if "ALTO" in nivel_riesgo:
                            color_badge = "red"
                        elif "MEDIO" in nivel_riesgo:
                            color_badge = "orange"
                        else:
                            color_badge = "green"
                        
                        # Mostrar badge del nivel de riesgo
                        
                        st.markdown(f":{color_badge}-badge[{nivel_riesgo}]")
                        
                        
                        # Mostrar cada sitio de este nivel de riesgo
                        for site in sitios_nivel:
                            site_data = datos['conteo_ejecutadas'][
                                datos['conteo_ejecutadas'][COL_SITE_ID] == site
                            ].sort_values("MES")
                            
                            total_perdidos = datos['mantenimientos_perdidos'].get(site, 0)
                            
                            site_name_row = datos['prioridad_df'][datos['prioridad_df'][COL_SITE_ID] == site]
                            site_name = site_name_row[COL_SITE].iloc[0] if not site_name_row.empty else site
                            
                            num_especialidades_eliminadas = len(datos['eliminadas'][site])
                            
                            with st.expander(
                                f"{site} — {site_name} — "
                                f"{num_especialidades_eliminadas} especialidad(es) eliminada(s), "
                                f"{total_perdidos} mttos perdidos"
                            ):
                                
                                # Especialidades eliminadas
                                st.write("**Detalle de especialidades eliminadas:**")
                                for esp in datos['eliminadas'][site]:
                                    serie_esp = site_data[esp].fillna(0).astype(int)
                                    max_hist = serie_esp.max()
                                    actual = serie_esp.iloc[-1] if len(serie_esp) > 0 else 0
                                    perdidos = max_hist - actual
                                    st.write(f"- **{esp}**: {perdidos} mttos perdidos (máx histórico: {max_hist}, actual: {actual})")
                                
                                st.markdown("---")
                                
                                # Gráfico de evolución
                                st.write("**Evolución temporal de especialidades realizadas:**")
                                columnas_grafico = [
                                    c for c in site_data.columns 
                                    if c not in [COL_SITE_ID, "MES", "TOTAL"]
                                ]
                                df_grafico = site_data.melt(
                                    id_vars=["MES"],
                                    value_vars=columnas_grafico,
                                    var_name="Especialidad",
                                    value_name="Cantidad"
                                )
                                st.bar_chart(df_grafico, x="MES", y="Cantidad", color="Especialidad", horizontal=True)
            else:
                st.success(f"No hay sitios de tipo {nombre_tab} con especialidades eliminadas")

def mostrar_sitios_con_menos_mantenimientos(datos):
    """Muestra sitios que tienen menos mantenimientos en comparación al mes anterior"""
    
    st.header("Sitios con Menos Mantenimientos vs Mes Anterior")
    st.caption("Se muestran sitios donde el total de mantenimientos realizados disminuyó respecto al mes inmediato anterior")
    
    grupos_prioridades = {
        "P1": "P_1", "P2": "P_2", "P3": "P_3",
        "D1": "D_1", "D2": "D_2", "D3": "D_3",
        "B1": "B_1", "B2": "B_2", "B3": "B_3"
    }
    
    tabs = st.tabs([f"Sites {k}" for k in grupos_prioridades.keys()])
    
    for (nombre_tab, codigo_prioridad), tab in zip(grupos_prioridades.items(), tabs):
        with tab:
            # Filtrar sitios de esta prioridad
            sitios_prioridad = datos['prioridad_df'][
                datos['prioridad_df'][COL_PRIORIDAD] == codigo_prioridad
            ][COL_SITE_ID].unique()
            
            # Sitios con tendencia decreciente en esta prioridad
            sitios_con_alerta = [
                s for s in sitios_prioridad 
                if s in datos['tendencias'] and "DECRECIENDO" in datos['tendencias'][s]["tendencia"]
            ]
            
            if sitios_con_alerta:
                st.write(f"**⚠️ {len(sitios_con_alerta)} sitios con menos mantenimientos en {nombre_tab}**")
                
                # Agrupar sitios por nivel de riesgo (igual que en la función anterior)
                sitios_por_riesgo = {
                    "ALTO RIESGO": [],
                    "MEDIO RIESGO": [],
                    "BAJO RIESGO": []
                }
                
                for site in sitios_con_alerta:
                    riesgo_sitio = datos['riesgos'].get(site, "BAJO RIESGO")
                    sitios_por_riesgo[riesgo_sitio].append(site)
                
                # Mostrar por grupos de riesgo
                for nivel_riesgo in ["ALTO RIESGO", "MEDIO RIESGO", "BAJO RIESGO"]:
                    sitios_nivel = sitios_por_riesgo[nivel_riesgo]
                    
                    if sitios_nivel:
                        # Determinar color del badge (igual que en la función anterior)
                        if "ALTO" in nivel_riesgo:
                            color_badge = "red"
                        elif "MEDIO" in nivel_riesgo:
                            color_badge = "orange"
                        else:
                            color_badge = "green"
                        
                        # Mostrar badge del nivel de riesgo
                        st.markdown(f":{color_badge}-badge[{nivel_riesgo}]")
                        
                        # Ordenar por mayor caída dentro de cada nivel de riesgo
                        sitios_ordenados = sorted(
                            sitios_nivel,
                            key=lambda s: abs(datos['tendencias'][s]['valor']),
                            reverse=True
                        )
                        
                        # Mostrar cada sitio de este nivel de riesgo
                        for site in sitios_ordenados:
                            site_data = datos['conteo_ejecutadas'][
                                datos['conteo_ejecutadas'][COL_SITE_ID] == site
                            ].sort_values("MES")
                            
                            site_name_row = datos['prioridad_df'][datos['prioridad_df'][COL_SITE_ID] == site]
                            site_name = site_name_row[COL_SITE].iloc[0] if not site_name_row.empty else site
                            
                            tend = datos['tendencias'][site]
                            caida = abs(tend['valor'])
                            
                            with st.expander(
                                f"{site} — {site_name} — "
                                f"Cayó {caida:.0f} mantenimiento(s)"
                            ):
                                # Mostrar diferencia con mes anterior
                                if site in datos.get('diferencias_mtto', {}):
                                    dif_info = datos['diferencias_mtto'][site]
                                    
                                    col_dif1, col_dif2, col_dif3 = st.columns(3)
                                    
                                    with col_dif1:
                                        st.metric("Mes Anterior", f"{dif_info['mes_anterior']}")
                                    with col_dif2:
                                        st.metric("Mes Actual", f"{dif_info['mes_actual']}")
                                    with col_dif3:
                                        delta_valor = dif_info['diferencia']
                                        st.metric(
                                            "Diferencia", 
                                            f"{delta_valor:+d}",
                                            delta=f"{delta_valor:+d} mttos"
                                        )
                                    
                                # Mostrar también la tabla detallada
                                columnas_grafico = [
                                    c for c in site_data.columns 
                                    if c not in [COL_SITE_ID, "MES", "TOTAL"]
                                ]
                                
                                tabla_detallada = site_data[["MES"] + columnas_grafico].set_index("MES")
                                
                                st.write("**Visualización gráfica:**")
                                df_grafico = site_data.melt(
                                    id_vars=["MES"],
                                    value_vars=columnas_grafico,
                                    var_name="Especialidad",
                                    value_name="Cantidad"
                                )
                                st.bar_chart(df_grafico, x="MES", y="Cantidad", color="Especialidad", horizontal=True)
                                st.dataframe(tabla_detallada, width="stretch")
                                
            else:
                st.success(f"No hay sitios de tipo {nombre_tab} con menos mantenimientos el ultimo mes ")
# === PÁGINA DE DETALLE POR ESPECIALIDAD ===
def pagina_especialidades():
    st.title("Análisis por Especialidad")
    
    datos = st.session_state.datos
    
    if datos is None:
        st.info(" Por favor carga un archivo Excel para iniciar el análisis.")
        return
    
    st.header("Análisis Detallado por Especialidad")
    
    # Seleccionar especialidad
    especialidad_seleccionada = st.selectbox(
        "Selecciona una especialidad para analizar:",
        ESPECIALIDADES
    )
    
    if especialidad_seleccionada:
        # Filtrar datos por especialidad
        df_especialidad = datos['df'][datos['df'][COL_ESPECIALIDAD] == especialidad_seleccionada]
        
        # Métricas de la especialidad
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            total_mttos = len(df_especialidad)
            st.metric("Total Mantenimientos", total_mttos, border=True)
        
        with col2:
            ejecutados = len(df_especialidad[df_especialidad[COL_ESTADO].str.lower() == "ejecutado"])
            porcentaje_ejecutado = (ejecutados / total_mttos * 100) if total_mttos > 0 else 0
            st.metric("Ejecutados", ejecutados, f"{porcentaje_ejecutado:.1f}%", border=True)
        
        with col3:
            pendientes = len(df_especialidad[df_especialidad[COL_ESTADO].str.lower() == "pendiente"])
            porcentaje_pendiente = (pendientes / total_mttos * 100) if total_mttos > 0 else 0
            st.metric("Pendientes", pendientes, f"{porcentaje_pendiente:.1f}%", border=True)
        
        with col4:
            cancelados = len(df_especialidad[df_especialidad[COL_ESTADO].str.lower() == "cancelado"])
            porcentaje_cancelado = (cancelados / total_mttos * 100) if total_mttos > 0 else 0
            st.metric("Cancelados", cancelados, f"{porcentaje_cancelado:.1f}%", delta_color="inverse", border=True)
        
        # Evolución temporal
        st.subheader(f"Evolución Temporal - {especialidad_seleccionada}")
        evolucion = df_especialidad.groupby(["MES", COL_ESTADO]).size().unstack(fill_value=0)
        if not evolucion.empty:
            st.line_chart(evolucion)
        else:
            st.info("No hay datos suficientes para mostrar la evolución temporal")
        
        # Top sitios con problemas en esta especialidad
        st.subheader(f"Sitios con Problemas - {especialidad_seleccionada}")
        
        sitios_problema = []
        for site in datos['eliminadas']:
            if especialidad_seleccionada in datos['eliminadas'][site]:
                sitios_problema.append(site)
        
        if sitios_problema:
            st.write(f"**{len(sitios_problema)} sitios tienen problemas con {especialidad_seleccionada}:**")
            for sitio in sitios_problema:
                st.write(f"- {sitio}")
        else:
            st.success(f"   No hay sitios con problemas de {especialidad_seleccionada}")

# === CONFIGURACIÓN PRINCIPAL ===
def main():
    # Inicializar datos en session_state si no existen
    if 'datos' not in st.session_state:
        st.session_state.datos = cargar_datos()
    
    # Inicializar página actual si no existe
    if 'pagina_actual' not in st.session_state:
        st.session_state.pagina_actual = "Inicio"
    
    # MOSTRAR PILLS SOLO SI NO ESTAMOS EN INICIO
    if st.session_state.pagina_actual != "Inicio":
        # Control de navegación con pills
        pagina = st.pills(
            " ",
            ["Volver a Inicio", "Búsqueda por Site ID", "Mantenimientos Pendientes", 
             "Sitios Problemáticos", "Análisis FLM", "Especialidades"],
            selection_mode="single",
            width="stretch"
        )
        
        # Mapear la selección a nombres de página
        mapeo_paginas = {
            "Volver a Inicio": "Inicio",
            "Búsqueda por Site ID": "Búsqueda por Site ID",
            "Mantenimientos Pendientes": "Mantenimientos Pendientes",
            "Sitios Problemáticos": "Sitios Problemáticos",
            "Análisis FLM": "Análisis FLM",
            "Especialidades": "Especialidades"
        }
        
        # Actualizar página actual si hay selección
        if pagina:
            st.session_state.pagina_actual = mapeo_paginas[pagina]
    
    # Navegación entre páginas
    if st.session_state.pagina_actual == "Inicio":
        pagina_bienvenida()
    elif st.session_state.pagina_actual == "Búsqueda por Site ID":
        pagina_busqueda_site()
    elif st.session_state.pagina_actual == "Análisis FLM":
        pagina_analisis_flm()
    elif st.session_state.pagina_actual == "Sitios Problemáticos":
        pagina_sitios_problematicos()
    elif st.session_state.pagina_actual == "Especialidades":
        pagina_especialidades()
    elif st.session_state.pagina_actual == "Mantenimientos Pendientes":
        pagina_pendientes()

if __name__ == "__main__":
    main()