# === Importación de librerías ===
import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime
from pathlib import Path
import io

# === CONFIGURACIÓN INICIAL ===
st.set_page_config(page_title="Control de Mantenimientos", layout="wide")

# === CONSTANTES ===
# ARCHIVO variable will be set dynamically based on uploaded file
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
def cargar_datos(uploaded_file):
    """Carga y procesa los datos desde el archivo subido"""
    try:
        if uploaded_file is not None:
            # Leer el archivo subido
            df = pd.read_excel(uploaded_file, sheet_name=HOJA)
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
    except Exception as e:
        st.error(f"Error al cargar el archivo: {str(e)}")
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
    
    # === FILE UPLOADER - ADDED HERE ===
    st.markdown("---")
    st.subheader("📤 Cargar Archivo de Datos")
    
    uploaded_file = st.file_uploader(
        "Sube tu archivo Excel de mantenimientos preventivos", 
        type=["xlsx"], 
        help="El archivo debe contener la hoja 'Data' con los datos de mantenimientos"
    )
    
    if uploaded_file is not None:
        # Store the uploaded file in session state
        st.session_state.uploaded_file = uploaded_file
        st.success("✅ Archivo cargado exitosamente!")
        
        # Load data
        with st.spinner("Procesando datos..."):
            datos = cargar_datos(uploaded_file)
            if datos is not None:
                st.session_state.datos = datos
                st.rerun()
            else:
                st.error("Error al procesar el archivo. Verifica el formato.")
    
    # Only show the navigation buttons if data is loaded
    if 'datos' in st.session_state and st.session_state.datos is not None:
        datos = st.session_state.datos
        
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
    else:
        st.info("👆 Por favor, sube un archivo Excel para comenzar el análisis.")

# === REST OF YOUR CODE REMAINS EXACTLY THE SAME ===
# [All your existing page functions: pagina_busqueda_site(), pagina_pendientes(), etc.]
# [Keep all the existing functions exactly as they are]

# === CONFIGURACIÓN PRINCIPAL ===
def main():
    # Initialize session state variables
    if 'datos' not in st.session_state:
        st.session_state.datos = None
    
    if 'pagina_actual' not in st.session_state:
        st.session_state.pagina_actual = "Inicio"
    
    if 'uploaded_file' not in st.session_state:
        st.session_state.uploaded_file = None
    
    # Only show navigation pills if we have data and are not on the home page
    if (st.session_state.datos is not None and 
        st.session_state.pagina_actual != "Inicio"):
        
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
        if st.session_state.datos is not None:
            pagina_busqueda_site()
        else:
            st.error("No hay datos cargados. Por favor, ve a Inicio y sube un archivo.")
            if st.button("Volver a Inicio"):
                st.session_state.pagina_actual = "Inicio"
                st.rerun()
    elif st.session_state.pagina_actual == "Análisis FLM":
        if st.session_state.datos is not None:
            pagina_analisis_flm()
        else:
            st.error("No hay datos cargados. Por favor, ve a Inicio y sube un archivo.")
            if st.button("Volver a Inicio"):
                st.session_state.pagina_actual = "Inicio"
                st.rerun()
    elif st.session_state.pagina_actual == "Sitios Problemáticos":
        if st.session_state.datos is not None:
            pagina_sitios_problematicos()
        else:
            st.error("No hay datos cargados. Por favor, ve a Inicio y sube un archivo.")
            if st.button("Volver a Inicio"):
                st.session_state.pagina_actual = "Inicio"
                st.rerun()
    elif st.session_state.pagina_actual == "Especialidades":
        if st.session_state.datos is not None:
            pagina_especialidades()
        else:
            st.error("No hay datos cargados. Por favor, ve a Inicio y sube un archivo.")
            if st.button("Volver a Inicio"):
                st.session_state.pagina_actual = "Inicio"
                st.rerun()
    elif st.session_state.pagina_actual == "Mantenimientos Pendientes":
        if st.session_state.datos is not None:
            pagina_pendientes()
        else:
            st.error("No hay datos cargados. Por favor, ve a Inicio y sube un archivo.")
            if st.button("Volver a Inicio"):
                st.session_state.pagina_actual = "Inicio"
                st.rerun()

if __name__ == "__main__":
    main()