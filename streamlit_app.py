# === Importación de librerías ===
import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime
import math

# === CONFIGURACIÓN INICIAL ===
st.set_page_config(page_title="Control de Mantenimientos", layout="wide")

# === CONSTANTES ===
ARCHIVO = "preventivo_2febrero.xlsx"
HOJA = "Data"

ARCHIVO_ANULACIONES = "Anulaciones.xlsx"
HOJA_ANULACIONES = "anulaciones"

ARCHIVO_FRECUENCIAS= "frecuencias_2025.xlsx"
HOJA_FRECUENCIAS = "Hoja1"

# Nombres de columnas
COL_ESPECIALIDAD = "SUB_ESPECIALIDAD"
COL_SITE_ID = "Site Id"
COL_SITE = "Site Id Name"
COL_PRIORIDAD = "Site Priority"
COL_CONTRATISTA = "Contratista Sitio"
COL_ESTADO = "ESTADO"
COL_FECHA = "2_MES_PROGRA"
COL_FLM_ESPECIFICO = "SUP_FLM_2"
COL_COMPLETE_TIME = "Complete Time"

columnas_relevantes = [
    COL_ESPECIALIDAD, COL_SITE_ID, COL_SITE, COL_PRIORIDAD,
    COL_CONTRATISTA, COL_ESTADO, COL_FECHA, COL_FLM_ESPECIFICO, 
    COL_COMPLETE_TIME
]

columnas_anulaciones = [
    "Site Id", "Mes de la anulación", "Especialidad eliminada", "Tipo de anulación", "Justificación", 
]


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

def obtener_ultimo_mes_valido(df):
    """
    Regla:
    - Para cada sitio, analizar mes por mes.
    - Un mes es válido si tiene >= 80% de ejecuciones.
    - Devolver el último mes válido, si no: 'NO 2025'.
    """
    df = df.copy()
    df["MES_DT"] = pd.to_datetime(df["MES"], format="%Y-%m")

    # Agrupar Site – Mes – Estado
    resumen = (
        df.groupby([COL_SITE, "MES", "MES_DT"])[COL_ESTADO]
        .value_counts()
        .unstack(fill_value=0)
        .reset_index()
    )

    # Identificar automáticamente solo las columnas numéricas de estados
    columnas_estados = [
        col for col in resumen.columns 
        if col not in [COL_SITE, "MES", "MES_DT"]
    ]

    # Asegurar que existan columnas esperadas
    for estado in ["Ejecutado", "Cancelado", "Pendiente"]:
        if estado not in columnas_estados:
            resumen[estado] = 0
            columnas_estados.append(estado)

    # Calcular total y porcentaje
    resumen["TOTAL"] = resumen[columnas_estados].sum(axis=1)
    resumen["EJEC"] = resumen["Ejecutado"]
    resumen["PORC"] = resumen["EJEC"] / resumen["TOTAL"]

    resultados = []

    for site, data in resumen.groupby(COL_SITE):
        data = data.sort_values("MES_DT", ascending=False)

        mes_valido = data[data["PORC"] >= 0.80].head(1)

        if mes_valido.empty:
            resultados.append([site, "NO 2025"])
        else:
            resultados.append([site, mes_valido.iloc[0]["MES"]])

    return pd.DataFrame(resultados, columns=[COL_SITE, "ULTIMO_MES_VALIDO"])


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

def detectar_sitios_con_ejecucion_incompleta(df, conteo_df, col_site_id):
    """
    Detecta sitios que:
    1. Ya tuvieron al menos un mantenimiento ejecutado este mes
    2. El último mantenimiento fue hace más de 2 días
    3. Aún no completan la cantidad de mantenimientos del mes anterior
    
    Returns:
        dict: Diccionario con información de sitios con ejecución incompleta
    """
    from datetime import datetime, timedelta
    
    # Obtener el mes actual en formato YYYY-MM
    fecha_actual = datetime.now()
    mes_actual_str = fecha_actual.strftime("%Y-%m")
    
    sitios_incompletos = {}
    
    # Filtrar solo mantenimientos ejecutados
    df_ejecutados = df[df[COL_ESTADO].str.lower() == "ejecutado"].copy()
    
    # Convertir Complete Time a datetime
    df_ejecutados[COL_COMPLETE_TIME] = pd.to_datetime(
        df_ejecutados[COL_COMPLETE_TIME], 
        errors='coerce'
    )
    
    for site in conteo_df[col_site_id].unique():
        site_data = conteo_df[conteo_df[col_site_id] == site].sort_values("MES")
        
        # Verificar que tenga al menos 2 meses de historial
        if len(site_data) < 2:
            continue
        
        # Obtener datos del mes anterior
        mes_anterior_total = site_data.iloc[-2]["TOTAL"]
        
        # Filtrar mantenimientos del sitio en el mes actual
        mttos_mes_actual = df_ejecutados[
            (df_ejecutados[col_site_id] == site) &
            (df_ejecutados["MES"] == mes_actual_str)
        ]
        
        if mttos_mes_actual.empty:
            continue
        
        # Obtener el último mantenimiento ejecutado
        ultimo_mtto = mttos_mes_actual[COL_COMPLETE_TIME].max()
        
        # Verificar si es válido
        if pd.isna(ultimo_mtto):
            continue
        
        # Calcular días desde el último mantenimiento
        dias_desde_ultimo = (fecha_actual - ultimo_mtto).days
        
        # Cantidad de mantenimientos ejecutados este mes
        mttos_realizados_mes_actual = len(mttos_mes_actual)
        
        # Criterios:
        # 1. Tiene al menos 1 mantenimiento este mes
        # 2. Último mtto hace más de 2 días
        # 3. No alcanza la cantidad del mes anterior
        if (mttos_realizados_mes_actual > 0 and 
            dias_desde_ultimo > 2 and 
            mttos_realizados_mes_actual < mes_anterior_total):
            
            faltantes = mes_anterior_total - mttos_realizados_mes_actual
            
            sitios_incompletos[site] = {
                "mes_anterior_total": mes_anterior_total,
                "mes_actual_realizados": mttos_realizados_mes_actual,
                "faltantes": faltantes,
                "ultimo_mtto_fecha": ultimo_mtto.strftime("%Y-%m-%d"),
                "dias_desde_ultimo": dias_desde_ultimo,
                "porcentaje_completado": round(
                    (mttos_realizados_mes_actual / mes_anterior_total) * 100, 1
                )
            }
    
    return sitios_incompletos

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

# === FUNCIÓN DE PREDICCIÓN ===
def predecir_mantenimientos_especialidad(df, df_frecuencias, especialidad, meses_a_predecir=1):
    """
    Predice la cantidad de mantenimientos esperados para una especialidad en los próximos meses.
    
    Args:
        df: DataFrame con los datos de mantenimientos
        df_frecuencias: DataFrame con las frecuencias anuales por sitio
        especialidad: Especialidad a predecir
        meses_a_predecir: Cantidad de meses a predecir (default: 2)
    
    Returns:
        DataFrame con predicciones por mes
    """
    # Filtrar solo mantenimientos ejecutados de la especialidad
    df_esp = df[(df[COL_ESPECIALIDAD] == especialidad) & 
                (df[COL_ESTADO].str.lower() == "ejecutado")].copy()
    
    if df_esp.empty:
        return pd.DataFrame()
    
    # Convertir MES a datetime
    df_esp["MES_DT"] = pd.to_datetime(df_esp["MES"], format="%Y-%m")
    
    # Calcular promedio de mantenimientos por sitio-especialidad
    promedios_por_sitio = df_esp.groupby(COL_SITE_ID).size().to_dict()
    conteo_meses_por_sitio = df_esp.groupby(COL_SITE_ID)["MES"].nunique().to_dict()
    
    # Calcular promedio real (total mttos / cantidad de meses con datos)
    promedio_mttos_por_sitio = {
        site: math.ceil(promedios_por_sitio[site] / conteo_meses_por_sitio.get(site, 1))
        for site in promedios_por_sitio
    }
    
    # Obtener el último mes con datos
    ultimo_mes = df_esp["MES_DT"].max()
    
    # Preparar diccionario de frecuencias
    frecuencias_dict = df_frecuencias.set_index(COL_SITE_ID)["frecuencia"].to_dict() if not df_frecuencias.empty else {}
    
    predicciones = []
    
    # Para cada mes a predecir
    for i in range(1, meses_a_predecir + 1):
        mes_prediccion = ultimo_mes + pd.DateOffset(months=i)
        mes_str = mes_prediccion.strftime("%Y-%m")
        
        total_esperado = 0
        sitios_con_mtto_esperado = []
        
        # Para cada sitio único en los datos
        for site in df_esp[COL_SITE_ID].unique():
            # Obtener último mantenimiento del sitio para esta especialidad
            ultimos_mttos_sitio = df_esp[df_esp[COL_SITE_ID] == site].sort_values("MES_DT")
            
            if ultimos_mttos_sitio.empty:
                continue
            
            ultimo_mtto_sitio = ultimos_mttos_sitio["MES_DT"].max()
            
            # Obtener frecuencia del sitio (default: 0 si no está en el archivo)
            frecuencia_anual = frecuencias_dict.get(site, 0)
            
            # Calcular meses entre mantenimientos
            meses_entre_mttos = 12 / frecuencia_anual if frecuencia_anual > 0 else 0
            
            # Calcular cuántos meses han pasado desde el último mtto
            meses_desde_ultimo = (mes_prediccion.year - ultimo_mtto_sitio.year) * 12 + \
                                (mes_prediccion.month - ultimo_mtto_sitio.month)
            
            # Si ya debería tener mantenimiento (±1 mes de tolerancia)
            if meses_desde_ultimo == meses_entre_mttos:
                promedio_sitio = promedio_mttos_por_sitio.get(site, 1)
                total_esperado += promedio_sitio
                sitios_con_mtto_esperado.append({
                    "site": site,
                    "ultimo_mtto": ultimo_mtto_sitio.strftime("%Y-%m"),
                    "meses_transcurridos": meses_desde_ultimo,
                    "frecuencia_esperada_meses": round(meses_entre_mttos, 1),
                    "mttos_esperados": round(promedio_sitio, 2)
                })
        
        predicciones.append({
            "mes": mes_str,
            "total_esperado": round(total_esperado, 1),
            "cantidad_sitios": len(sitios_con_mtto_esperado),
            "detalle_sitios": sitios_con_mtto_esperado
        })
    
    return pd.DataFrame(predicciones)

# === CARGA Y PROCESAMIENTO DE DATOS (se ejecuta una sola vez) ===
@st.cache_data
def cargar_datos():
    """Carga y procesa los datos una sola vez"""
    if ARCHIVO:
        df = pd.read_excel(ARCHIVO, sheet_name=HOJA)
        df.columns = df.columns.str.strip()

        df_frecuencias = pd.read_excel(ARCHIVO_FRECUENCIAS, sheet_name=HOJA_FRECUENCIAS)
        df_frecuencias.columns = df_frecuencias.columns.str.strip()

        df_anulaciones =pd.read_excel(ARCHIVO_ANULACIONES, sheet_name=HOJA_ANULACIONES)
        df_anulaciones.columns = df_anulaciones.columns.str.strip()

        # Filtrar el DataFrame para que solo queden las columnas relevantes para el análisis 
        df = df[columnas_relevantes]
        df_anulaciones = df_anulaciones[columnas_anulaciones]

        # Preparar columna de fecha
        df[COL_FECHA] = df[COL_FECHA].astype(str).str.strip().str.lower()
        df["MES"] = df[COL_FECHA].apply(convertir_mes_ano)

        
        # Filtrar por estado
        df_ejecutados = df[df[COL_ESTADO].str.lower() == "ejecutado"]
        df_cancelados = df[df[COL_ESTADO].str.lower() == "cancelado"]
        df_pendientes = df[df[COL_ESTADO].str.lower() == "pendiente"]

        #Filtrar por prioridad
        df_P1 = df[df[COL_PRIORIDAD].str.lower() == "p_1"]
        
        
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
        sitios_incompletos = detectar_sitios_con_ejecucion_incompleta(df, conteo_ejecutadas, COL_SITE_ID)  
        
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
            'df_frecuencias': df_frecuencias,  # ← ESTA LÍNEA ES NUEVA
            'conteo_ejecutadas': conteo_ejecutadas,
            'eliminadas': eliminadas,
            'mantenimientos_perdidos': mantenimientos_perdidos,
            'diferencias_mtto': diferencias_mtto,
            'tendencias': tendencias,
            'sitios_incompletos': sitios_incompletos,
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
        
        if st.button("**Sitios Problemáticos**", 
                     width="stretch",  type="primary", icon=":material/error:"):
            st.session_state.pagina_actual = "Sitios Problemáticos"
            st.rerun()

        if st.button("**Búsqueda por Site ID**", 
                     width="stretch",  type="primary", icon=":material/search:"):
            st.session_state.pagina_actual = "Búsqueda por Site ID"
            st.rerun()

        if st.button("**Generar Reporte**", 
                     width="stretch",  type="primary", icon=":material/download:"):
            st.session_state.pagina_actual = "Generar Reporte"
            st.rerun()
    
    with col2:
        if st.button("**Análisis por Especialidades**", 
                     width="stretch", type="primary", icon=":material/finance_mode:"):
            st.session_state.pagina_actual = "Especialidades"
            st.rerun()

        if st.button("**Mantenimientos Pendientes**", 
                     width="stretch",  type="primary", icon=":material/pending_actions:"):
            st.session_state.pagina_actual = "Mantenimientos Pendientes"
            st.rerun()
        
        if st.button("**Anulaciones**", 
                        width="stretch",  type="primary", icon=":material/cancel:"):
                st.session_state.pagina_actual = "Anulaciones"
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
        st.subheader("Evolución Histórica de Mantenimientos")
        
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

        # === ANULACIONES REGISTRADAS ===
        try:
            df_anulaciones_full = pd.read_excel(ARCHIVO_ANULACIONES, sheet_name=HOJA_ANULACIONES)
            df_anulaciones_full.columns = df_anulaciones_full.columns.str.strip()
            
            anulaciones_site = df_anulaciones_full[df_anulaciones_full["Site Id"] == site_buscado]
            
            if not anulaciones_site.empty:
                st.markdown("---")
                st.subheader("Anulaciones Registradas")
                
                # Mostrar resumen
                col_anul1, col_anul2 = st.columns(2)
                
                with col_anul1:
                    total_anulaciones = len(anulaciones_site)
                    st.metric("Total de Anulaciones", total_anulaciones, border=True)
                
                with col_anul2:
                    especialidades_anuladas = anulaciones_site["Especialidad eliminada"].nunique()
                    st.metric("Especialidades Anuladas", especialidades_anuladas, border=True)
                
                # Mostrar tabla de anulaciones
                st.write("**Detalle de las anulaciones:**")
                
                
                
                styled_anulaciones = anulaciones_site[["Especialidad eliminada", "Tipo de anulación", "Justificación"]]
                
                st.dataframe(styled_anulaciones, hide_index=True, width='stretch')
        
        except FileNotFoundError:
            pass  # Si no existe el archivo, simplemente no mostramos la sección
        except Exception as e:
            st.warning(f"No se pudieron cargar las anulaciones: {str(e)}")
        
        
        # === ALERTAS DE PENDIENTES ===
        alertas_site = [a for a in datos['alertas_pendientes'] if a['site ID'] == site_buscado]
        
        if alertas_site:
            st.markdown("---")
            st.subheader("Mantenimientos Pendientes sin Ejecutar")
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


def pagina_sitios_problematicos():
    st.title("Sitios Problemáticos")
    
    datos = st.session_state.datos
    
    if datos is None:
        st.info(" Por favor carga un archivo Excel para iniciar el análisis.")
        return
    
    col_btn1, col_btn2, col_btn3 = st.columns(3)
    
    with col_btn1:
        if st.button("Especialidades Eliminadas", width="stretch", type="primary"):
            st.session_state.tipo_problema = "eliminadas"
    
    with col_btn2:
        if st.button("Menos Mantenimientos vs Mes Anterior", width="stretch" , type="primary"):
            st.session_state.tipo_problema = "decreciendo"
    
    with col_btn3:
        if st.button("Ejecución Incompleta Este Mes", width="stretch", type="primary"):
            st.session_state.tipo_problema = "incompletos"
    
    # Inicializar tipo de problema si no existe
    if 'tipo_problema' not in st.session_state:
        st.session_state.tipo_problema = " "
    
    # === MOSTRAR SEGÚN TIPO DE PROBLEMA SELECCIONADO ===
    tipo_seleccionado = st.session_state.tipo_problema
    
    if tipo_seleccionado == "eliminadas":
        mostrar_sitios_con_especialidades_eliminadas(datos)
    elif tipo_seleccionado == "incompletos":
        mostrar_sitios_con_ejecucion_incompleta(datos)
    else:
        mostrar_sitios_con_menos_mantenimientos(datos)


def mostrar_sitios_con_ejecucion_incompleta(datos):
    """Muestra sitios que iniciaron mantenimientos este mes pero no completan la cantidad del mes anterior"""
    
    st.header("Sitios con Ejecución Incompleta Este Mes")
    st.caption("Sitios que ya ejecutaron al menos un mantenimiento hace más de 2 días, pero aún no alcanzan la cantidad del mes anterior")
    
    sitios_incompletos = datos.get('sitios_incompletos', {})
    
    if not sitios_incompletos:
        st.success("✅ No hay sitios con ejecución incompleta detectados")
        return
    
    st.markdown("---")
    
    # Cargar anulaciones
    try:
        df_anulaciones_full = pd.read_excel(ARCHIVO_ANULACIONES, sheet_name=HOJA_ANULACIONES)
        df_anulaciones_full.columns = df_anulaciones_full.columns.str.strip()
        tiene_anulaciones = True
    except:
        tiene_anulaciones = False

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
            
            # Sitios incompletos en esta prioridad
            sitios_con_alerta = [
                s for s in sitios_prioridad 
                if s in sitios_incompletos
            ]
            
            if sitios_con_alerta:
                st.write(f"**⚠️ {len(sitios_con_alerta)} sitios con ejecución incompleta en {nombre_tab}**")
                
                # Ordenar por porcentaje completado (los más atrasados primero)
                sitios_ordenados = sorted(
                    sitios_con_alerta,
                    key=lambda s: sitios_incompletos[s]['porcentaje_completado']
                )
                
                for site in sitios_ordenados:
                    info = sitios_incompletos[site]
                    
                    site_name_row = datos['prioridad_df'][datos['prioridad_df'][COL_SITE_ID] == site]
                    site_name = site_name_row[COL_SITE].iloc[0] if not site_name_row.empty else site
                    
                    # Determinar color según porcentaje
                    if info['porcentaje_completado'] < 50:
                        color_badge = "red"
                        nivel = "CRÍTICO"
                    elif info['porcentaje_completado'] < 75:
                        color_badge = "orange"
                        nivel = "ALERTA"
                    else:
                        color_badge = "yellow"
                        nivel = "MONITOREO"
                    
                    with st.expander(
                        f"{site} — {site_name} — "
                        f"{info['porcentaje_completado']}% completado, "
                        f"{info['faltantes']} mttos faltantes"
                    ):
                        st.markdown(f":{color_badge}-badge[{nivel}]")
                        
                        # Métricas
                        col1, col2, col3, col4 = st.columns(4)
                        
                        with col1:
                            st.metric(
                                "Mes Anterior",
                                info['mes_anterior_total'],
                                border=True
                            )
                        
                        with col2:
                            st.metric(
                                "Realizados Este Mes",
                                info['mes_actual_realizados'],
                                f"{info['porcentaje_completado']}%",
                                border=True
                            )
                        
                        with col3:
                            st.metric(
                                "Faltantes",
                                info['faltantes'],
                                delta_color="inverse",
                                border=True
                            )
                        
                        with col4:
                            st.metric(
                                "Días Desde Último Mtto",
                                info['dias_desde_ultimo'],
                                border=True
                            )
                        
                        st.caption(f"Último mantenimiento: {info['ultimo_mtto_fecha']}")
                        
                        # Verificar si hay anulaciones registradas
                        if tiene_anulaciones:
                            anulaciones_sitio = df_anulaciones_full[df_anulaciones_full["Site Id"] == site]
                            
                            if not anulaciones_sitio.empty:
                                st.markdown("---")
                                st.write("**📋 Anulaciones registradas:**")
                                
                                for _, anulacion in anulaciones_sitio.iterrows():
                                    tipo_color = "🔴" if "Sitio Completo" in str(anulacion["Tipo de anulación"]) else "🟡"
                                    st.write(f"{tipo_color} **{anulacion['Especialidad eliminada']}** — {anulacion['Tipo de anulación']}")
                                    st.caption(f"Justificación: {anulacion['Justificación']}")
                        
                        st.markdown("---")
                        
                        # Mostrar evolución histórica
                        site_data = datos['conteo_ejecutadas'][
                            datos['conteo_ejecutadas'][COL_SITE_ID] == site
                        ].sort_values("MES")
                        
                        if not site_data.empty:
                            st.write("**Evolución histórica:**")
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
                st.success(f"✅ No hay sitios de tipo {nombre_tab} con ejecución incompleta")

def generar_reporte_ejecucion_incompleta(datos):
    """
    Genera un reporte detallado en Excel de los sitios con ejecución incompleta,
    incluyendo las especialidades faltantes, mes de ejecución, FLM asignado y anulaciones.
    """
    from datetime import datetime
    
    sitios_incompletos = datos.get('sitios_incompletos', {})
    
    if not sitios_incompletos:
        return None
    
    mes_actual_str = datetime.now().strftime("%Y-%m")
    
    # Cargar archivo de anulaciones
    try:
        df_anulaciones_full = pd.read_excel(ARCHIVO_ANULACIONES, sheet_name=HOJA_ANULACIONES)
        df_anulaciones_full.columns = df_anulaciones_full.columns.str.strip()
        tiene_anulaciones = True
    except:
        tiene_anulaciones = False
        df_anulaciones_full = pd.DataFrame()
    
    reporte_data = []
    
    for site_id, info in sitios_incompletos.items():
        # Obtener información del sitio
        site_info = datos['prioridad_df'][datos['prioridad_df'][COL_SITE_ID] == site_id]
        
        if site_info.empty:
            continue
        
        site_name = site_info[COL_SITE].iloc[0]
        site_prioridad = site_info[COL_PRIORIDAD].iloc[0]
        
        # Obtener FLM del sitio
        df_site = datos['df'][datos['df'][COL_SITE_ID] == site_id]
        flm_sitio = df_site[COL_FLM_ESPECIFICO].iloc[0] if not df_site.empty else "Sin Asignar"
        
        # Obtener especialidades ejecutadas este mes
        df_ejecutados_mes_actual = datos['df_ejecutados'][
            (datos['df_ejecutados'][COL_SITE_ID] == site_id) &
            (datos['df_ejecutados']["MES"] == mes_actual_str)
        ]
        
        especialidades_ejecutadas_mes_actual = set(df_ejecutados_mes_actual[COL_ESPECIALIDAD].unique())
        
        # Obtener especialidades ejecutadas mes anterior
        conteo_site = datos['conteo_ejecutadas'][
            datos['conteo_ejecutadas'][COL_SITE_ID] == site_id
        ].sort_values("MES")
        
        if len(conteo_site) < 2:
            continue
        
        mes_anterior = conteo_site.iloc[-2]
        
        # Identificar especialidades faltantes (que se hicieron mes anterior pero no este mes)
        especialidades_faltantes = []
        for especialidad in ESPECIALIDADES:
            if especialidad in conteo_site.columns:
                cantidad_mes_anterior = mes_anterior[especialidad]
                cantidad_mes_actual = len(df_ejecutados_mes_actual[
                    df_ejecutados_mes_actual[COL_ESPECIALIDAD] == especialidad
                ])
                
                if cantidad_mes_anterior > 0 and cantidad_mes_actual < cantidad_mes_anterior:
                    faltante = cantidad_mes_anterior - cantidad_mes_actual
                    especialidades_faltantes.append(f"{especialidad} ({faltante})")
        
        # Verificar si hay anulaciones registradas para este sitio
        anulaciones_info = "No"
        tiene_anulacion = False
        
        if tiene_anulaciones and not df_anulaciones_full.empty:
            anulaciones_sitio = df_anulaciones_full[df_anulaciones_full["Site Id"] == site_id]
            
            if not anulaciones_sitio.empty:
                tiene_anulacion = True
                # Crear lista de anulaciones con tipo
                lista_anulaciones = []
                for _, anulacion in anulaciones_sitio.iterrows():
                    especialidad_anulada = anulacion['Especialidad eliminada']
                    tipo_anulacion = anulacion['Tipo de anulación']
                    lista_anulaciones.append(f"{especialidad_anulada} ({tipo_anulacion})")
                
                anulaciones_info = "; ".join(lista_anulaciones)
        
        # Determinar nivel de criticidad
        if info['porcentaje_completado'] < 50:
            criticidad = "CRÍTICO"
        elif info['porcentaje_completado'] < 75:
            criticidad = "ALERTA"
        else:
            criticidad = "MONITOREO"
        
        reporte_data.append({
            "Site ID": site_id,
            "Site Name": site_name,
            "Prioridad": site_prioridad,
            "FLM": flm_sitio,
            "Mes Analizado": mes_actual_str,
            "Mttos Mes Anterior": info['mes_anterior_total'],
            "Mttos Realizados Este Mes": info['mes_actual_realizados'],
            "Mttos Faltantes": info['faltantes'],
            "% Completado": f"{info['porcentaje_completado']}%",
            "Especialidades Faltantes": ", ".join(especialidades_faltantes) if especialidades_faltantes else "Ninguna",
            "Tiene Anulaciones": "Sí" if tiene_anulacion else "No",
            "Detalle Anulaciones": anulaciones_info,
            "Último Mantenimiento": info['ultimo_mtto_fecha'],
            "Días Desde Último Mtto": info['dias_desde_ultimo'],
            "Criticidad": criticidad
        })
    
    df_reporte = pd.DataFrame(reporte_data)
    
    # Ordenar por criticidad y luego por porcentaje completado
    orden_criticidad = {"CRÍTICO": 0, "ALERTA": 1, "MONITOREO": 2}
    df_reporte['orden'] = df_reporte['Criticidad'].map(orden_criticidad)
    df_reporte = df_reporte.sort_values(['orden', '% Completado']).drop('orden', axis=1)
    
    return df_reporte

def generar_reporte_mantenimientos_perdidos(datos, meses_seleccionados=None):
    """
    Genera un DataFrame con los mantenimientos perdidos por sitio y especialidad.
    Analiza una lista de meses específicos vs su promedio histórico.
    
    Args:
        datos: Diccionario con los datos procesados
        meses_seleccionados: Lista de meses en formato ["YYYY-MM", ...] o un solo string.
                             Si es None, usa el último mes disponible.
    """
    # 1. Normalizar la entrada a una lista de meses
    if meses_seleccionados is None:
        meses_seleccionados = [datos['conteo_ejecutadas']['MES'].max()]
    elif isinstance(meses_seleccionados, str):
        meses_seleccionados = [meses_seleccionados]
    
    reporte_acumulado = []
    
    # 2. Iterar por cada mes en la lista
    for mes_actual in meses_seleccionados:
        
        for site in datos['conteo_ejecutadas'][COL_SITE_ID].unique():
            site_data = datos['conteo_ejecutadas'][
                datos['conteo_ejecutadas'][COL_SITE_ID] == site
            ].sort_values("MES")
            
            # Verificar si el sitio tiene datos para el mes en evaluación
            if mes_actual not in site_data['MES'].values:
                continue
            
            # Obtener datos hasta el mes evaluado (inclusive) para calcular el histórico
            site_data_hasta_mes = site_data[site_data['MES'] <= mes_actual]
            
            if len(site_data_hasta_mes) < 2:
                continue
            
            mantenimientos_perdidos_texto = []
            tiene_caida = False
            
            # Evaluación por especialidad
            for especialidad in ESPECIALIDADES:
                if especialidad not in site_data_hasta_mes.columns:
                    continue
                
                serie = site_data_hasta_mes[especialidad].fillna(0).astype(int)
                
                # Promedio histórico (excluyendo el mes actual de la iteración)
                # Tomamos todos los registros previos al último en 'site_data_hasta_mes'
                promedio_historico = serie.iloc[:-1].mean()
                valor_mes_actual = serie.iloc[-1]
                
                diferencia = valor_mes_actual - promedio_historico
                
                if diferencia < -0.5:
                    tiene_caida = True
                    diferencia_redondeada = int(round(diferencia))
                    mantenimientos_perdidos_texto.append(f"{diferencia_redondeada} mtto {especialidad}")
            
            # 3. Agregar al reporte si se detectó caída en ese mes
            if tiene_caida and mantenimientos_perdidos_texto:
                
                site_info = datos['prioridad_df'][datos['prioridad_df'][COL_SITE_ID] == site]
                
                # Extraer Site Name y FLM
                site_name = site_info[COL_SITE].iloc[0] if not site_info.empty else "N/A"
                # Cambia 'FLM' por el nombre exacto de la columna en tu archivo (ej. 'Vendor' o 'Responsable')
                flm_name = site_info['FLM'].iloc[0] if 'FLM' in site_info.columns and not site_info.empty else "Sin Asignar"
                
                total_actual = site_data.iloc[-1]['TOTAL']
                promedio_total_h = site_data.iloc[:-1]['TOTAL'].mean()
                
                reporte_acumulado.append({
                    "Mes Analizado": mes_actual,
                    "Site Id": site,
                    "Site Name": site_name,
                    "FLM": COL_FLM_ESPECIFICO,  
                    "Mantenimientos Perdidos": ", ".join(mantenimientos_perdidos_texto),
                    "Total Mes": int(total_actual),
                    "Promedio Histórico": round(promedio_total_h, 1),
                    "Diferencia": round(total_actual - promedio_total_h, 1)
                })
    
    # 4. Consolidar y ordenar
    df_reporte = pd.DataFrame(reporte_acumulado)
    if not df_reporte.empty:
        # Ordenamos por mes (asc) y luego por la caída más fuerte (asc)
        df_reporte = df_reporte.sort_values('Mes Analizado', ascending=True)
    
    return df_reporte


def mostrar_sitios_con_especialidades_eliminadas(datos):
    """Muestra sitios que tienen especialidades eliminadas (3+ meses consecutivos sin hacerse)"""
    
    st.header("Sitios con Especialidades Eliminadas")
    st.caption("Se consideran eliminadas las especialidades que no se ejecutaron durante 3 o más meses consecutivos respecto a su máximo histórico")
    

    st.markdown("---")
    
    # Cargar anulaciones
    try:
        df_anulaciones_full = pd.read_excel(ARCHIVO_ANULACIONES, sheet_name=HOJA_ANULACIONES)
        df_anulaciones_full.columns = df_anulaciones_full.columns.str.strip()
        tiene_anulaciones = True
    except:
        tiene_anulaciones = False

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
                                
                                # Verificar si hay anulaciones registradas
                                if tiene_anulaciones:
                                    anulaciones_sitio = df_anulaciones_full[df_anulaciones_full["Site Id"] == site]
                                    
                                    if not anulaciones_sitio.empty:
                                        st.markdown("---")
                                        st.write("**📋 Anulaciones registradas para este sitio:**")
                                        
                                        for _, anulacion in anulaciones_sitio.iterrows():
                                            tipo_color = "🔴" if "Sitio completo" in str(anulacion["Tipo de anulación"]) else "🟡"
                                            st.write(f"{tipo_color} **{anulacion['Especialidad eliminada']}** — {anulacion['Tipo de anulación']}")
                                            st.caption(f"Justificación: {anulacion['Justificación']}")
                                
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
    st.caption("Se muestran sitios donde el total de mantenimientos realizados disminuyó respecto al promedio histórico")
    

    
    # Cargar anulaciones
    try:
        df_anulaciones_full = pd.read_excel(ARCHIVO_ANULACIONES, sheet_name=HOJA_ANULACIONES)
        df_anulaciones_full.columns = df_anulaciones_full.columns.str.strip()
        tiene_anulaciones = True
    except:
        tiene_anulaciones = False

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
                                
                                # Verificar si hay anulaciones registradas
                                if tiene_anulaciones:
                                    anulaciones_sitio = df_anulaciones_full[df_anulaciones_full["Site Id"] == site]
                                    
                                    if not anulaciones_sitio.empty:
                                        st.markdown("---")
                                        st.write("**📋 Anulaciones registradas para este sitio:**")
                                        
                                        for _, anulacion in anulaciones_sitio.iterrows():
                                            tipo_color = "🔴" if "Sitio completo" in str(anulacion["Tipo de anulación"]) else "🟡"
                                            st.write(f"{tipo_color} **{anulacion['Especialidad eliminada']}** — {anulacion['Tipo de anulación']}")
                                            st.caption(f"Justificación: {anulacion['Justificación']}")
                                
                                # Mostrar también la tabla detallada
                                columnas_grafico = [
                                    c for c in site_data.columns 
                                    if c not in [COL_SITE_ID, "MES", "TOTAL"]
                                ]
                                
                                tabla_detallada = site_data[["MES"] + columnas_grafico].set_index("MES")
                                
                                st.markdown("---")
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

        # === PREDICCIÓN DE MANTENIMIENTOS ===
        st.markdown("---")
        st.subheader(f"📈 Predicción de Mantenimientos - {especialidad_seleccionada}")
        
        # Obtener predicciones
        predicciones = predecir_mantenimientos_especialidad(
            datos['df'], 
            datos['df_frecuencias'], 
            especialidad_seleccionada,
            meses_a_predecir=1
        )
        
        if not predicciones.empty:
            st.write("**Mantenimientos esperados para los próximos meses:**")
            
            # Mostrar métricas de predicción
            cols_pred = st.columns(len(predicciones))
            
            for idx, (col, row) in enumerate(zip(cols_pred, predicciones.itertuples())):
                with col:
                    st.metric(
                        label=f"🗓️ {row.mes}",
                        value=f"{row.total_esperado:.0f} mttos",
                        delta=f"{row.cantidad_sitios} sitios",
                        border=True
                    )
            
            # Mostrar detalles de cada mes predicho
            for idx, row in predicciones.iterrows():
                with st.expander(f"Ver detalle de {row['mes']} ({row['cantidad_sitios']} sitios programados)"):
                    if row['detalle_sitios']:
                        df_detalle = pd.DataFrame(row['detalle_sitios'])
                        
                        # Renombrar columnas para mejor visualización
                        df_detalle = df_detalle.rename(columns={
                            'site': 'Site ID',
                            'ultimo_mtto': 'Último Mtto',
                            'meses_transcurridos': 'Meses Transcurridos',
                            'frecuencia_esperada_meses': 'Cada cuantos meses le toca mtto',
                            'mttos_esperados': 'Mttos Esperados'
                        })
                        
                        st.dataframe(df_detalle, hide_index=True, width="stretch")
                        
                        st.caption(f"💡 **Total esperado para {row['mes']}:** {row['total_esperado']:.1f} mantenimientos")
                    else:
                        st.info("No hay sitios programados para este mes según las frecuencias")
            
            # Comparación histórica vs predicción
            st.markdown("---")
            st.subheader("📊 Comparación: Histórico vs Predicción")
            
            # Obtener datos históricos del último año
            df_historico = df_especialidad[
                df_especialidad[COL_ESTADO].str.lower() == "ejecutado"
            ].groupby("MES").size().reset_index(name="ejecutados")
            
            # Combinar histórico con predicción
            if not df_historico.empty:
                df_historico = df_historico.tail(6)  # Últimos 6 meses
                
                # Agregar predicciones
                for _, pred in predicciones.iterrows():
                    df_historico = pd.concat([
                        df_historico,
                        pd.DataFrame([{
                            "MES": pred['mes'],
                            "ejecutados": pred['total_esperado']
                        }])
                    ], ignore_index=True)
                
                # Crear gráfico
                st.line_chart(df_historico.set_index("MES")["ejecutados"])
                
                st.caption("📌 Los últimos puntos de la gráfica corresponden a las predicciones")
        else:
            st.warning("No hay suficientes datos para generar predicciones para esta especialidad")
        
        # Top sitios con problemas en esta especialidad
        st.markdown("---")
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

# === PÁGINA DE REGISTRO DE LAS ANULACIONES ===
def pagina_anulaciones():
    st.title("Detalle de las anulaciones reportadas por los FLM")
    
    datos = st.session_state.datos
    
    if datos is None:
        st.info("⚠️ Por favor carga un archivo Excel para iniciar el análisis.")
        return
    
    # Cargar el archivo de anulaciones
    try:
        df_anulaciones = pd.read_excel(ARCHIVO_ANULACIONES, sheet_name=HOJA_ANULACIONES)
        df_anulaciones.columns = df_anulaciones.columns.str.strip()
        df_anulaciones = df_anulaciones[columnas_anulaciones]

        
        if df_anulaciones.empty:
            st.warning("No hay registros de anulaciones disponibles")
            return
        
        # Métricas generales
        st.subheader("Resumen")
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            total_anulaciones = len(df_anulaciones)
            st.metric("Total de Anulaciones", total_anulaciones, border=True)
        
        with col2:
            sitios_afectados = df_anulaciones["Site Id"].nunique()
            st.metric("Sitios Afectados", sitios_afectados, border=True)
        
        with col3:
            especialidades_anuladas = df_anulaciones["Especialidad eliminada"].nunique()
            st.metric("Especialidades Anuladas", especialidades_anuladas, border=True)
        
        st.markdown("---")
        
        # Filtros
        st.subheader("Filtros")
        
        col_filtro1, col_filtro2 = st.columns(2)
        
        with col_filtro1:
            tipo_anulacion_filtro = st.multiselect(
                "Filtrar por Tipo de Anulación:",
                options=df_anulaciones["Tipo de anulación"].unique().tolist(),
                default=df_anulaciones["Tipo de anulación"].unique().tolist()
            )
        
        with col_filtro2:
            especialidad_filtro = st.multiselect(
                "Filtrar por Especialidad:",
                options=df_anulaciones["Especialidad eliminada"].unique().tolist(),
                default=df_anulaciones["Especialidad eliminada"].unique().tolist()
            )
        
        # Aplicar filtros
        df_filtrado = df_anulaciones[
            (df_anulaciones["Tipo de anulación"].isin(tipo_anulacion_filtro)) &
            (df_anulaciones["Especialidad eliminada"].isin(especialidad_filtro))
        ]
        
        st.markdown("---")
        
        # Mostrar tabla completa
        st.subheader(f"📋 Registro de Anulaciones ({len(df_filtrado)} registros)")
        
        # Función para aplicar estilos según tipo de anulación
        def aplicar_estilos_anulaciones(df):
            styles = pd.DataFrame('', index=df.index, columns=df.columns)
            
            if 'Tipo de anulación' in df.columns:
                for idx in df.index:
                    tipo = df.loc[idx, 'Tipo de anulación']
                    
                    if 'Sitio Completo' in str(tipo) or 'permanente' in str(tipo):
                        styles.loc[idx, 'Tipo de anulación'] = 'background-color: #fee2e2; color: #991b1b; font-weight: bold'
                    elif 'Temporal' in str(tipo) or 'temporal' in str(tipo):
                        styles.loc[idx, 'Tipo de anulación'] = 'background-color: #fef3c7; color: #92400e; font-weight: bold'
            
            return styles
        
        # Aplicar estilos
        styled_anulaciones = df_filtrado.style.apply(aplicar_estilos_anulaciones, axis=None)
        
        st.dataframe(styled_anulaciones, hide_index=True, width='stretch')
        
        # Análisis adicional
        st.markdown("---")
        st.subheader("Análisis por Tipo de Anulación")
        
        tipos_count = df_filtrado["Tipo de anulación"].value_counts()
        
        col_chart1, col_chart2 = st.columns(2)
        
        with col_chart1:
            st.write("**Distribución por Tipo:**")
            st.bar_chart(tipos_count)
        
        with col_chart2:
            st.write("**Distribución por Especialidad:**")
            esp_count = df_filtrado["Especialidad eliminada"].value_counts()
            st.bar_chart(esp_count)
        
        # Top sitios con más anulaciones
        st.markdown("---")
        st.subheader("Sitios con Más Anulaciones")
        
        top_sitios = df_filtrado["Site Id"].value_counts().head(10)
        
        if not top_sitios.empty:
            for site_id, count in top_sitios.items():
                anulaciones_sitio = df_filtrado[df_filtrado["Site Id"] == site_id]
                
                # Obtener nombre del sitio
                site_name_row = datos['prioridad_df'][datos['prioridad_df'][COL_SITE_ID] == site_id]
                site_name = site_name_row[COL_SITE].iloc[0] if not site_name_row.empty else site_id
                
                with st.expander(f"{site_id} — {site_name} ({count} anulaciones)"):
                    st.dataframe(
                        anulaciones_sitio[["Especialidad eliminada", "Tipo de anulación", "Justificación"]], 
                        hide_index=True,
                        width='stretch'
                    )
        
    except FileNotFoundError:
        st.error(f"❌ No se encontró el archivo: {ARCHIVO_ANULACIONES}")
    except Exception as e:
        st.error(f"❌ Error al cargar las anulaciones: {str(e)}")

# === PÁGINA DE REGISTRO DE LAS ANULACIONES ===
# === PÁGINA DE GENERAR REPORTES ===
def pagina_reporte():
    st.title("Reportes para la Auditoría")
    
    datos = st.session_state.datos
    
    if datos is None:
        st.info(" Por favor carga un archivo Excel para iniciar el análisis.")
        return
    
    # Botones para seleccionar tipo de reporte
    col_btn1, col_btn2 = st.columns(2)
    
    with col_btn1:
        if st.button("Mantenimientos Perdidos", width="stretch", type="primary"):
            st.session_state.tipo_reporte = "perdidos"
    
    with col_btn2:
        if st.button("Ejecución Incompleta", width="stretch", type="primary"):
            st.session_state.tipo_reporte = "incompleta"
    
    # Inicializar tipo de reporte si no existe
    if 'tipo_reporte' not in st.session_state:
        st.session_state.tipo_reporte = "perdidos"
    
    st.markdown("---")
    
    # === MOSTRAR SEGÚN TIPO DE REPORTE SELECCIONADO ===
    tipo_seleccionado = st.session_state.tipo_reporte
    
    if tipo_seleccionado == "perdidos":
        mostrar_reporte_mantenimientos_perdidos(datos)
    else:
        mostrar_reporte_ejecucion_incompleta(datos)


def mostrar_reporte_mantenimientos_perdidos(datos):
    """Muestra la sección de reporte de mantenimientos perdidos"""
    
    st.header("Reporte de Mantenimientos Perdidos")
    
    # Obtener lista de meses disponibles
    meses_disponibles = sorted(datos['conteo_ejecutadas']['MES'].unique(), reverse=True)
    
    col_mes, col_boton_generar = st.columns([2, 1])
    
    with col_mes:
        # Cambiamos selectbox por multiselect
        meses_seleccionados = st.multiselect(
            "Selecciona los meses a analizar:",
            options=meses_disponibles,
            default=[meses_disponibles[0]], # Por defecto selecciona el más reciente
            help="Puedes seleccionar varios meses. El reporte comparará cada mes contra su respectivo promedio histórico."
        )
    
    with col_boton_generar:
        st.write("") # Espaciadores
        st.write("") 
        # El botón ahora procesará la lista completa
        generar_reporte = st.button("🔄 Generar Reporte", type="secondary")
    
    # Generar y mostrar preview del reporte
    if meses_seleccionados:
        # La función que modificamos antes ahora recibe la lista
        df_reporte = generar_reporte_mantenimientos_perdidos(datos, meses_seleccionados)
        
        if not df_reporte.empty:
            
            # Preparar descarga en memoria
            from io import BytesIO
            buffer = BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                df_reporte.to_excel(writer, index=False, sheet_name='Mantenimientos Perdidos')
            buffer.seek(0)

            # Nombre del archivo dinámico basado en la cantidad de meses
            nombre_archivo = f"reporte_mantenimientos_{len(meses_seleccionados)}_meses.xlsx"
            if len(meses_seleccionados) == 1:
                nombre_archivo = f"reporte_mantenimientos_perdidos_{meses_seleccionados[0]}.xlsx"

            #boton de descarga del reporte
            st.download_button(
                label=f" Descargar Reporte Completo (Excel)",
                data=buffer,
                file_name=nombre_archivo,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary"
            )
            # Mostrar preview
            st.write(f"**Vista previa del reporte consolidado ({len(df_reporte)} registros encontrados):**")
            st.dataframe(df_reporte.head(10), hide_index=True, width='stretch')
            
            if len(df_reporte) > 10:
                st.caption(f"📋 Mostrando los primeros 10 registros. Descarga el archivo para ver el análisis de todos los meses seleccionados.")
            
            
            st.caption(f"Se analizaron {len(meses_seleccionados)} meses: {', '.join(meses_seleccionados)}")
        else:
            st.success(f"✅ No hay sitios con caídas significativas en los meses seleccionados: {', '.join(meses_seleccionados)}")


def mostrar_reporte_ejecucion_incompleta(datos):
    """Muestra la sección de reporte de ejecución incompleta"""
    
    st.header("Reporte de Ejecución Incompleta")
    st.caption("Sitios que ya iniciaron mantenimientos este mes pero no completan la cantidad del mes anterior")
    
    sitios_incompletos = datos.get('sitios_incompletos', {})
    
    if not sitios_incompletos or len(sitios_incompletos) == 0:
        st.success("✅ No hay sitios con ejecución incompleta detectados en este momento")
    else:
        # Generar el reporte
        df_reporte_incompleto = generar_reporte_ejecucion_incompleta(datos)
        
        if df_reporte_incompleto is not None and not df_reporte_incompleto.empty:
            # Botón de descarga
            from io import BytesIO
            from datetime import datetime
            
            buffer = BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                df_reporte_incompleto.to_excel(writer, index=False, sheet_name='Ejecución Incompleta')
            
            buffer.seek(0)
            
            fecha_reporte = datetime.now().strftime("%Y-%m-%d")
            
            st.download_button(
                label="Descargar Reporte Completo de Sitios con ejecución incompleta (Excel)",
                data=buffer,
                file_name=f"reporte_ejecucion_incompleta_{fecha_reporte}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary",
                width='stretch'
            )
            
            # Vista previa del reporte
            st.write(f"**Vista previa del reporte ({len(df_reporte_incompleto)} sitios con ejecución incompleta):**")
            
            # Aplicar estilos al dataframe
            def aplicar_estilos_criticidad(df):
                styles = pd.DataFrame('', index=df.index, columns=df.columns)
                
                if 'Criticidad' in df.columns:
                    for idx in df.index:
                        criticidad = df.loc[idx, 'Criticidad']
                        
                        if criticidad == 'CRÍTICO':
                            styles.loc[idx, 'Criticidad'] = 'background-color: #fee2e2; color: #991b1b; font-weight: bold'
                        elif criticidad == 'ALERTA':
                            styles.loc[idx, 'Criticidad'] = 'background-color: #fef3c7; color: #92400e; font-weight: bold'
                        else:
                            styles.loc[idx, 'Criticidad'] = 'background-color: #d1fae5; color: #065f46; font-weight: bold'
                
                return styles
            
            styled_df = df_reporte_incompleto.head(10).style.apply(aplicar_estilos_criticidad, axis=None)
            st.dataframe(styled_df, hide_index=True, width='stretch')
        
        else:
            st.info("No se pudo generar el reporte. Verifica que haya datos disponibles.")
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
            ["Volver al Inicio", "Búsqueda por Site ID", "Mantenimientos Pendientes", 
             "Sitios Problemáticos",  "Especialidades", "Anulaciones", "Generar Reporte"],
            selection_mode="single",
            width="stretch"
        )
        
        # Mapear la selección a nombres de página
        mapeo_paginas = {
            "Volver al Inicio": "Inicio",
            "Búsqueda por Site ID": "Búsqueda por Site ID",
            "Mantenimientos Pendientes": "Mantenimientos Pendientes",
            "Sitios Problemáticos": "Sitios Problemáticos",
            "Especialidades": "Especialidades",
            "Anulaciones": "Anulaciones", 
            "Generar Reporte": "Generar Reporte"
        }
        
        # Actualizar página actual si hay selección
        if pagina:
            st.session_state.pagina_actual = mapeo_paginas[pagina]
    
    # Navegación entre páginas
    if st.session_state.pagina_actual == "Inicio":
        pagina_bienvenida()
    elif st.session_state.pagina_actual == "Búsqueda por Site ID":
        pagina_busqueda_site()
    
    elif st.session_state.pagina_actual == "Sitios Problemáticos":
        pagina_sitios_problematicos()
    elif st.session_state.pagina_actual == "Especialidades":
        pagina_especialidades()
    elif st.session_state.pagina_actual == "Mantenimientos Pendientes":
        pagina_pendientes()
    elif st.session_state.pagina_actual == "Anulaciones":
        pagina_anulaciones()
    elif st.session_state.pagina_actual == "Generar Reporte":
        pagina_reporte()

if __name__ == "__main__":
    main()