# Control TV

Mando en el navegador para una Samsung Smart TV con Tizen (de 2016 en adelante). Cada persona lo ejecuta en su ordenador, en la misma Wi-Fi que su tele, y guarda ahí sus propios datos.

No funciona con LG, Sony, Roku ni con una Samsung anterior a Tizen.

## Docker

No hace falta Docker ni ningún contenedor. La tele solo acepta órdenes desde la red de casa. Este programa es un script de Python que se arranca en ese ordenador y escucha solo en `127.0.0.1`.

## Qué necesitas

- Python 3.10 o superior.
- El ordenador y la tele en la misma Wi-Fi.
- En la tele, permiso para el control por red. Al pulsar Permitir sale un aviso en la pantalla y hay que aceptarlo.

## Arrancar

En la carpeta del proyecto:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 mando.py
```

En Windows, el entorno virtual se activa con `.venv\Scripts\activate` y el programa se arranca con `py mando.py`.

Se abre el navegador en http://127.0.0.1:8765. Para cerrarlo, vuelve a la terminal y pulsa Ctrl+C.

La primera vez no hay ninguna tele. Entra en Ajustes y rellena:

1. Nombre. El que quieras, por ejemplo Salón.
2. IP de la tele. En la tele: Ajustes, General, Red, Estado de la red. El nombre del menú cambia un poco según el modelo.
3. MAC, solo si quieres usar Encender. En la tele: Ajustes, Soporte, Acerca de esta TV, Dir. MAC inalámbrica.
4. Guardar.
5. Permitir, y acepta el aviso que sale en la tele.

A partir de ahí el mando ya envía las teclas del mando Samsung: números, volumen, canal, dirección, colores y el resto. Las flechas, Enter, Esc y +/− también valen desde el teclado.

En Apps salen Netflix, YouTube, Prime Video, Disney+, HBO Max, Spotify, Apple TV e Internet. Elegir abre más (Movistar, Orange, Atresplayer, RTVE, DAZN y otras) para marcar las que quieras. Cargar las de esta tele lee las instaladas en esa Samsung. Si una no aparece, se puede añadir con su nombre y su id.

El botón Descargar instala una ventana de esta misma página en el ordenador. No es un archivo para el móvil. El programa de la terminal tiene que seguir abierto; si lo cierras, la ventana no llega a la tele.

## Dónde quedan los datos

Al arrancar se crea `config.json` en esta carpeta. Ahí están el nombre, la IP, la MAC y el permiso que aceptaste en la tele. Ese archivo no se sube al repositorio. No lo copies a un servidor ni lo compartas: quien lo tenga puede mandar tu tele mientras esté encendida y en la misma red.

## Encender desde el mando

Apagar envía el botón de encendido de la tele. Encender manda un aviso por la red a la MAC que guardaste. En muchas teles Samsung hay que activar antes, en la red, la opción de encender con el móvil. Por Wi-Fi a menudo no responde, porque la tele apagada deja de escuchar. Por cable de red es más fiable.

## mandotv.kyadigital.es (web en internet + agente en casa)

La interfaz puede estar en un servidor, pero **las órdenes a la tele las manda un agente en tu Wi‑Fi**. En un PC o Raspberry de la misma red que la Samsung:

```bash
cd control-tv
source .venv/bin/activate   # tras pip install -r requirements.txt
export MANDO_AGENT_URL='wss://mandotv.kyadigital.es/agent/ws'
export MANDO_AGENT_TOKEN='el-token-que-te-den'   # no lo publiques
python3 home_agent.py
```

Deja esa terminal abierta. Luego abre https://mandotv.kyadigital.es, configura la tele y pulsa **Permitir**.

## Qué no hace este programa

- No controla teles fuera de tu red sin el agente en casa.
- No guarda los datos de otras personas en ningún servidor compartido.
