# Balance Hídrico Periódico 

Versión "de producción" del notebook `balance_hidrico_gee`, pensada para
correr sola, de forma periódica, en una PC Windows (Task Scheduler). Misma
física agronómica que la planilla Excel y el notebook, con dos cambios de
fuente de datos:

| Variable                 | Antes (notebook)        | Ahora                                                        |
|---------------------------|--------------------------|--------------------------------------------------------------|
| NDVI                      | GEE (S2+L8+L9+MODIS)     | **Copernicus Data Space Ecosystem** (Sentinel-2 L2A, Statistical API) |
| Días sin imagen           | se repetía el último valor | se interpola entre observaciones reales                      |
| Manejo del lote           | archivo fijo             | mapa en la página web, con guardado y ejecución desde ahí     |
| Precipitación y ETo       | GEE (ERA5-Land)          | **Copernicus Climate Data Store** (AgERA5)                    |
| AOI                       | subida manual cada vez   | shapefile `aoi/lote_20.shp` fijo en el proyecto               |

El script es **incremental**: cada corrida solo pide y procesa los días
nuevos desde la última vez, arrancando desde el estado (AU real y
profundidad de raíz) que dejó la corrida anterior — no se reprocesa la
campaña completa cada vez.

## 1. Estructura

```
balance_hidrico_periodico/
├── aoi/lote_20.shp (+ .shx .dbf .prj .cpg)   # polígono del lote
├── config.yaml                                # toda la configuración
├── requirements.txt
├── run_balance_hidrico.bat                    # para Task Scheduler
├── src/
│   ├── aoi.py            # carga del lote (GeoJSON o shapefile)
│   ├── suelo.py          # parámetros de suelo (de BH p-Pons.xlsx)
│   ├── balance.py         # fórmulas del balance (Kc, Ks, modelo diario)
│   ├── ndvi_sentinelhub.py# NDVI vía Copernicus Data Space Ecosystem
│   ├── mapas_ndvi.py      # mosaico de imágenes NDVI del lote
│   ├── clima_agera5.py    # precipitación + ETo vía CDS / AgERA5
│   ├── estado.py          # estado.json + CSV histórico
│   ├── auth_cdse.py       # login OAuth2 en CDSE
│   ├── config.py
│   └── main.py            # orquestador (esto es lo que corre Task Scheduler)
├── data/                  # (se crea sola) estado.json + CSV histórico
└── logs/                  # (se crea sola) logs de cada corrida
```

## 2. Instalación (una sola vez)

1. Instalar Python 3.11+ en la PC.
2. Abrir `cmd` en la carpeta del proyecto y crear un entorno virtual:
   ```
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   ```

## 3. Credenciales

### 3.1 Copernicus Data Space Ecosystem (NDVI)

1. Crear cuenta gratuita en <https://dataspace.copernicus.eu/>.
2. Ir a <https://shapps.dataspace.copernicus.eu/dashboard/> → **User
   Settings** → **OAuth clients** → **Create new OAuth client**.
3. Copiar el `client_id` y `client_secret` generados.
4. Definirlos como **variables de entorno de usuario** en Windows (así no
   quedan escritas en ningún archivo del proyecto):
   - Buscar "Editar las variables de entorno del sistema" → Variables de
     entorno → Nueva (en "Variables de usuario"):
     - `CDSE_CLIENT_ID` = tu client id
     - `CDSE_CLIENT_SECRET` = tu client secret

### 3.2 Copernicus Climate Data Store (precipitación + ETo)

1. Crear cuenta en <https://cds.climate.copernicus.eu/>.
2. Entrar una vez a la página del dataset
   <https://cds.climate.copernicus.eu/datasets/sis-agrometeorological-indicators>
   y aceptar la licencia ("Terms of use").
3. En tu perfil de CDS copiar tu API key personal.
4. Crear el archivo `C:\Users\<tu_usuario>\.cdsapirc` con:
   ```
   url: https://cds.climate.copernicus.eu/api
   key: TU_API_KEY_PERSONAL
   ```

> ⚠️ Las APIs de Copernicus cambian de tanto en tanto los nombres exactos de
> parámetros. Si `descargar_agera5()` empieza a fallar, entrar a la página
> del dataset, armar la consulta con el asistente ("Show API request") y
> pegar ese `request` dentro de `config.yaml` → `cds.request_template`, sin
> tocar el código.

## 4. Configurar el lote y la campaña

Editar `config.yaml`:
- `campana.fecha_siembra`, `au_real_inicial_mm`, `prof_raiz_inicial_cm`: solo
  se usan la **primera vez** (después el estado se guarda solo). Para
  arrancar una campaña nueva en el mismo lote, borrar `data/estado.json`.
- `balance.umbral_riego_pct`: umbral de alerta de riego.
- Si el suelo cambia, agregar una clave `suelo:` en `config.yaml` con la
  misma estructura que `SUELO_PROPIEDADES_DEFAULT` en `src/suelo.py`
  (por defecto usa la serie "Los llanos - Serie Oncativo" de `BH p-Pons.xlsx`).

## 5. Probar una corrida manual

```
venv\Scripts\activate
python -m src.main
```

Revisar `data/balance_hidrico_lote20.csv` y `logs/balance_hidrico.log`.

## 6. Programar la corrida periódica (Task Scheduler)

1. Abrir **Programador de Tareas** → **Crear tarea básica**.
2. Nombre: `Balance Hídrico Lote 20`.
3. Desencadenador: por ejemplo **Semanal**, cada 5 días (frecuencia
   razonable dado el revisit de Sentinel-2 y el rezago de AgERA5;
   correrlo todos los días no aporta datos nuevos).
4. Acción: **Iniciar un programa**.
   - Programa/script: ruta completa a `run_balance_hidrico.bat`
   - Iniciar en: la carpeta del proyecto (ej.
     `C:\Users\Diego\balance_hidrico_periodico`)
5. En las variables de entorno del usuario que ejecuta la tarea deben estar
   definidas `CDSE_CLIENT_ID` y `CDSE_CLIENT_SECRET` (punto 3.1).

Cada corrida:
- si no hay días nuevos disponibles (por el rezago de datos), no hace nada
  y lo deja en el log;
- si hay días nuevos, descarga NDVI + clima, corre el balance, actualiza
  `data/balance_hidrico_lote20.csv` y `data/estado.json`, y si el % de Agua
  Útil quedó por debajo del umbral, deja una alerta bien visible en el log.

## 6b. Cómo se trata el NDVI

Sentinel-2 pasa cada cinco días y las nubes agrandan los huecos, así que la
mayoría de los días no tiene imagen propia. El sistema hace tres cosas:

1. **Enmascara por píxel** con la banda SCL de Sentinel-2 L2A: descarta
   nubes, sombras de nube, cirros y nieve dentro del lote.
2. **Descarta la fecha entera** si menos del 70 % del lote quedó con píxeles
   válidos (`cdse.min_pixeles_validos_pct`). Con menos que eso el promedio
   describe la parte despejada, no el lote.
3. **Interpola linealmente** entre fechas con observación real. Antes se
   arrastraba el último valor, lo que convertía la curva en una escalera:
   durante el crecimiento subestimaba el NDVI y en senescencia lo
   sobreestimaba, y el Kc heredaba ese error.

El filtro de nubosidad de la escena completa está en 90 %
(`cdse.max_cloud_coverage`) a propósito: el enmascarado real lo hace el paso
1, píxel a píxel, así que un umbral bajo solo descartaría pasadas en las que
el lote podía estar despejado.

Los días posteriores a la última imagen no se pueden interpolar: se sostiene
el último valor y el log dice cuántos son.

## 7. Notas y limitaciones a tener en cuenta

- El AOI (`aoi/lote_20.shp`) descargado de Drive para armar este proyecto
  tenía el `.dbf` dañado (problema de esa copia puntual, no del formato).
  `src/aoi.py` ya contempla ese caso con un método de respaldo que lee la
  geometría igual (no necesitamos atributos, solo el polígono). Conviene
  igual reemplazar los 5 archivos por el shapefile original completo.
- AgERA5 tiene ~10 km de resolución: para un lote de ~40 ha el valor es
  representativo de la zona, no hiperlocal. Si más adelante se quiere mayor
  detalle espacial de lluvia, se puede sumar una fuente pluviométrica local
  (estación propia / IoT) como capa adicional en `df_clima`.
- Sentinel-2 no pasa todos los días (revisit ~5 días) y puede haber nubes.
  Ver la sección 6b sobre cómo se completan esos huecos. En un lote chico el
  problema se agrava: 2 ha son unos 200 píxeles, así que una nube pequeña
  tapa una fracción grande del lote.
- Los riegos reales (si se aplican) hoy quedan en 0 por defecto
  (`df_dias["riego_mm"] = 0.0` en `main.py`); si se registran en campo,
  ese es el lugar para cargarlos antes de correr el balance.
