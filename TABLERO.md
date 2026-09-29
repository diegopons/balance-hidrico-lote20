# Tablero web

El proyecto incluye una página web que muestra el balance en forma de tablero:
estado del día, perfil de suelo, evolución de la campaña y detalle diario.

Está en `docs/index.html`. No necesita servidor ni base de datos: lee
directamente el CSV que genera el sistema.

---

## Opción 1 — Verlo en tu computadora

Sirve para probarlo, o para consultarlo sin pasar por internet.

1. Descargá el repositorio a tu PC (botón verde **Code** → **Download ZIP**).
2. Descomprimí y entrá a la carpeta `docs`.
3. Abrí `index.html` con doble clic.

> Si el tablero aparece vacío al abrirlo con doble clic, es por una
> restricción de seguridad del navegador para archivos locales. Solución:
> abrí una consola en la carpeta `docs` y ejecutá `python -m http.server`,
> después entrá a `http://localhost:8000` en el navegador.

## Opción 2 — Publicarlo en internet con GitHub Pages (la elegida)

Para este proyecto se optó por **repositorio público + tablero publicado**.
GitHub publica la página en una dirección propia y se actualiza sola en cada
corrida.

1. En tu repositorio: **Settings** → menú izquierdo, **Pages**.
2. En "Source" elegí **Deploy from a branch**.
3. En "Branch" elegí `main`, y en la carpeta elegí **/docs**. Guardá.
4. Esperá uno o dos minutos. Arriba aparece la dirección, con el formato:
   `https://TU_USUARIO.github.io/balance-hidrico-lote20/`

Se abre desde cualquier navegador, incluido el celular.

### Qué implica que el repositorio sea público

**No queda expuesto:** las claves de Copernicus ni el token de Telegram.
Viven en los Secrets, cifrados, y GitHub además enmascara sus valores si
alguna vez aparecieran en un registro de ejecución.

**Sí queda visible:** la ubicación del lote (el polígono), la serie de datos
de agua útil, NDVI y lluvias, y los registros de cada corrida.

**A tener presente:** el historial de Git es permanente. Si alguna vez pegás
una clave dentro de un archivo y la subís, borrarla después no alcanza —
queda en el historial y hay que revocarla. Por eso el `.gitignore` ya excluye
`.cdsapirc` y `.env`. Mientras uses los Secrets, no hay problema.

**Ventaja:** los repositorios públicos tienen minutos de ejecución
ilimitados, así que correrlo a diario nunca roza ningún límite.

### El tablero no tiene contraseña

Una página de GitHub Pages es accesible para cualquiera que tenga el enlace.
No es un sistema con usuarios ni claves. En la práctica nadie va a dar con
esa dirección por casualidad, pero conviene saberlo antes de compartirla.

### Opcional

En **Settings** podés desactivar *Issues* y *Discussions* si no querés que
nadie abra hilos en el repositorio. No afecta en nada al funcionamiento.

---

## Qué muestra

**Estado del día.** La condición (Óptimo / Adecuado / Déficit / Crítico),
el agua útil en mm, cuánto falta para capacidad de campo, la profundidad de
raíz, el consumo del día y la lluvia de la última semana.

**Perfil del suelo.** Un corte del suelo hasta 2 metros, con la línea de
profundidad de raíz y una franja azul que representa qué proporción de la
capacidad está ocupada por agua disponible.

> La franja se llena de izquierda a derecha a propósito. Un llenado desde
> abajo daría a entender que el agua está acumulada en el fondo del perfil,
> como una napa, y no es eso: el agua útil está distribuida en toda la zona
> explorada por las raíces.

**La campaña hasta hoy.** El % de agua útil a lo largo de todo el ciclo,
con la banda roja marcando la zona por debajo del umbral de riego, y las
lluvias diarias colgando desde arriba.

**Vigor del cultivo.** La curva de NDVI de la campaña.

**Últimos catorce días.** Tabla con el detalle diario.

---

## Ajustes

Los parámetros del tablero están al principio del bloque `<script>` en
`docs/index.html`:

```javascript
const UMBRAL_RIEGO = 50;   // % de agua útil que dispara la alerta
const EFICIENCIA = 0.85;   // eficiencia de aplicación del riego
const PROF_MAX = 200;      // profundidad del perfil, en cm
```

Si los cambiás en `config.yaml` (para el script y las alertas de Telegram),
acordate de cambiarlos también acá para que el tablero muestre lo mismo.

Los colores están en el bloque `:root` del CSS, arriba de todo.

---

## Si el tablero dice "Todavía no hay resultados"

Significa que no encontró el archivo `docs/balance_hidrico_lote20.csv`.
Es lo esperable hasta que el sistema procese su primer día con datos: el
workflow copia el CSV a esa carpeta al final de cada corrida.

Para forzarlo: pestaña **Actions** → **Balance Hídrico Lote 20** →
**Run workflow**.
