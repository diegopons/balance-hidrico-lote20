@echo off
REM ============================================================
REM  Ejecuta el balance hidrico y queda listo para el Programador
REM  de Tareas de Windows. Ajustar las rutas segun donde se
REM  copie esta carpeta en la PC.
REM ============================================================

REM Carpeta del proyecto (donde esta este .bat)
cd /d "%~dp0"

REM --- Credenciales CDSE para esta sesion (mejor: definirlas como
REM     variables de entorno de USUARIO en Windows, asi no quedan
REM     escritas en este archivo). Si ya estan como variables de
REM     entorno permanentes, borrar las dos lineas SET de abajo.
REM SET CDSE_CLIENT_ID=tu_client_id
REM SET CDSE_CLIENT_SECRET=tu_client_secret

REM Activar entorno virtual (crear una vez con: python -m venv venv)
call venv\Scripts\activate.bat

python -m src.main >> logs\ultima_corrida.txt 2>&1

deactivate
