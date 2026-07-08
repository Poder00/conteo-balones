# -*- coding: utf-8 -*-
"""
CONTEO DE BALONES DE GLP - App Android (Kivy + NumPy, SIN OpenCV)
==================================================================
El celular cuenta los llenados solo, usando su propia camara.
El conteo se hace con NumPy puro (sin OpenCV, para que compile bien).

Flujo:
  1. Apertura de turno (nombre operador)
  2. Definir el area (ROI) sobre el video
  3. Capturar referencia del area vacia
  4. Conteo automatico (maquina de estados)
  5. Cierre de turno (nombre) -> resumen + guardado del reporte

Maquina de estados:
  VACIA -> CONFIRMANDO -> LLENANDO -> (conteo +1) -> VACIA
"""

import os
import time
import datetime
import json

from kivy.app import App
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.camera import Camera
from kivy.uix.widget import Widget
from kivy.graphics import Color, Line, Rectangle
from kivy.graphics.texture import Texture
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.utils import platform

import numpy as np

# ===========================================================================
# CONFIGURACION (calibrar en planta)
# ===========================================================================
UMBRAL_DIFERENCIA = 40          # 0-255: cuanto debe cambiar un pixel
PORCENTAJE_OCUPACION = 0.25     # fraccion del area que debe cambiar
SEGUNDOS_CONFIRMACION = 1.5
T_MINIMO_LLENADO_S = 15.0       # ~70% del ciclo real mas rapido
SEGUNDOS_VACIADO = 2.0

# Colores Triton
COL_FONDO = (0.239, 0.263, 0.286, 1)
COL_NARANJA = (0.941, 0.502, 0.098, 1)
COL_VERDE = (0.30, 0.69, 0.31, 1)
COL_TEXTO = (0.95, 0.95, 0.95, 1)


def carpeta_datos():
    if platform == 'android':
        from android.storage import app_storage_path
        base = app_storage_path()
    else:
        base = os.path.expanduser('~')
    ruta = os.path.join(base, 'conteo_balones_data')
    os.makedirs(ruta, exist_ok=True)
    return ruta


# ===========================================================================
# CONVERSIONES CON NUMPY (reemplazo de OpenCV)
# ===========================================================================
def a_gris(rgb_array):
    """Convierte un array RGB (alto, ancho, 3+) a escala de grises.
    Reemplaza cv2.cvtColor. Usa los pesos estandar de luminancia."""
    r = rgb_array[:, :, 0].astype(np.float32)
    g = rgb_array[:, :, 1].astype(np.float32)
    b = rgb_array[:, :, 2].astype(np.float32)
    gris = 0.299 * r + 0.587 * g + 0.114 * b
    return gris.astype(np.uint8)


def fraccion_diferente(referencia, actual, umbral):
    """Fraccion de pixeles que difieren de la referencia mas alla del umbral.
    Reemplaza cv2.absdiff + cv2.threshold + conteo."""
    if referencia.shape != actual.shape:
        # Recorte simple al minimo comun (evita dependencia de resize de cv2)
        h = min(referencia.shape[0], actual.shape[0])
        w = min(referencia.shape[1], actual.shape[1])
        referencia = referencia[:h, :w]
        actual = actual[:h, :w]
    diff = np.abs(referencia.astype(np.int16) - actual.astype(np.int16))
    cambiados = np.count_nonzero(diff >= umbral)
    total = diff.size
    return float(cambiados) / total if total > 0 else 0.0


# ===========================================================================
# MAQUINA DE ESTADOS DE CONTEO (identica a la original)
# ===========================================================================
class ContadorLlenado:
    def __init__(self):
        self.referencia = None
        self.estado = 'VACIA'
        self.conteo = 0
        self.t_ocupacion = None
        self.t_llenado = None
        self.t_vaciado = None
        self.ultima_fraccion = 0.0

    def set_referencia(self, gris):
        self.referencia = gris.copy()
        self.reset()

    def reset(self):
        self.estado = 'VACIA'
        self.conteo = 0
        self.t_ocupacion = None
        self.t_llenado = None
        self.t_vaciado = None

    def actualizar(self, gris):
        if self.referencia is None:
            return False
        ahora = time.time()
        frac = fraccion_diferente(self.referencia, gris, UMBRAL_DIFERENCIA)
        self.ultima_fraccion = frac
        ocupada = frac >= PORCENTAJE_OCUPACION

        if self.estado == 'VACIA':
            if ocupada:
                if self.t_ocupacion is None:
                    self.t_ocupacion = ahora
                elif ahora - self.t_ocupacion >= SEGUNDOS_CONFIRMACION:
                    self.estado = 'CONFIRMANDO'
            else:
                self.t_ocupacion = None
        elif self.estado == 'CONFIRMANDO':
            if ocupada:
                self.estado = 'LLENANDO'
                self.t_llenado = ahora
            else:
                self.estado = 'VACIA'
                self.t_ocupacion = None
        elif self.estado == 'LLENANDO':
            if not ocupada:
                if self.t_vaciado is None:
                    self.t_vaciado = ahora
                elif ahora - self.t_vaciado >= SEGUNDOS_VACIADO:
                    duracion = ahora - self.t_llenado
                    conto = duracion >= T_MINIMO_LLENADO_S
                    if conto:
                        self.conteo += 1
                    self.estado = 'VACIA'
                    self.t_ocupacion = None
                    self.t_llenado = None
                    self.t_vaciado = None
                    return conto
            else:
                self.t_vaciado = None
        return False


# ===========================================================================
# WIDGET QUE DIBUJA EL ROI SOBRE LA CAMARA
# ===========================================================================
class OverlayROI(Widget):
    """Se dibuja encima de la camara para mostrar el recuadro del area."""
    def __init__(self, pantalla, **kwargs):
        super().__init__(**kwargs)
        self.pantalla = pantalla
        Clock.schedule_interval(self._redibujar, 1.0 / 15.0)

    def _redibujar(self, dt):
        self.canvas.clear()
        p = self.pantalla
        with self.canvas:
            if p.contando:
                Color(*COL_VERDE)
            else:
                Color(*COL_NARANJA)
            x1, y1, x2, y2 = p.roi_pantalla()
            Line(rectangle=(x1, y1, x2 - x1, y2 - y1), width=2)


# ===========================================================================
# PANTALLA 1: APERTURA
# ===========================================================================
class PantallaApertura(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        lay = BoxLayout(orientation='vertical', padding=30, spacing=20)
        with self.canvas.before:
            Color(*COL_FONDO)
            self._r = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._u, size=self._u)

        lay.add_widget(Label(text='[b]APERTURA DE TURNO[/b]', markup=True,
                             font_size='26sp', color=COL_NARANJA, size_hint=(1, 0.2)))
        lay.add_widget(Label(text='Nombre del operador que abre:', color=COL_TEXTO,
                             font_size='18sp', size_hint=(1, 0.1)))
        self.inp = TextInput(hint_text='Ej: Juan Perez', multiline=False,
                             font_size='20sp', size_hint=(1, 0.15))
        lay.add_widget(self.inp)
        self.msg = Label(text='', color=COL_TEXTO, font_size='15sp', size_hint=(1, 0.25))
        lay.add_widget(self.msg)
        b = Button(text='INICIAR TURNO', font_size='22sp',
                   background_color=COL_NARANJA, size_hint=(1, 0.2))
        b.bind(on_press=self.iniciar)
        lay.add_widget(b)
        self.add_widget(lay)

    def _u(self, *a):
        self._r.pos = self.pos
        self._r.size = self.size

    def iniciar(self, *a):
        nombre = self.inp.text.strip()
        if not nombre:
            self.msg.text = 'Ingrese el nombre del operador.'
            return
        app = App.get_running_app()
        app.turno = {
            'operador_apertura': nombre,
            'hora_apertura': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }
        self.manager.current = 'conteo'


# ===========================================================================
# PANTALLA 2: CONTEO (camara + area + botones)
# ===========================================================================
class PantallaConteo(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.contador = ContadorLlenado()
        self.contando = False
        self.definiendo = False
        # ROI en fraccion (0-1) del area de la camara
        self.roi = [0.3, 0.3, 0.7, 0.7]
        self._arr = False
        self.cam = None

        self.lay = BoxLayout(orientation='vertical')
        self.add_widget(self.lay)

    def on_enter(self):
        # Construir solo una vez
        if self.cam is not None:
            return
        # Barra superior
        top = BoxLayout(size_hint=(1, 0.12), padding=6)
        with top.canvas.before:
            Color(0.15, 0.16, 0.18, 1)
            self._rt = Rectangle(pos=top.pos, size=top.size)
        top.bind(pos=lambda *a: setattr(self._rt, 'pos', top.pos),
                 size=lambda *a: setattr(self._rt, 'size', top.size))
        self.lbl_conteo = Label(text='[b]0[/b]', markup=True, font_size='40sp',
                                color=COL_NARANJA, size_hint=(0.4, 1))
        top.add_widget(self.lbl_conteo)
        self.lbl_estado = Label(text='Estado: --', color=COL_TEXTO,
                                font_size='14sp', size_hint=(0.6, 1))
        top.add_widget(self.lbl_estado)
        self.lay.add_widget(top)

        # Camara con overlay
        cont_cam = BoxLayout(size_hint=(1, 0.6))
        try:
            self.cam = Camera(play=True, resolution=(640, 480))
        except Exception as e:
            self.cam = Label(text='No se pudo abrir la camara:\n%s' % e,
                             color=COL_TEXTO)
        cont_cam.add_widget(self.cam)
        self.overlay = OverlayROI(self)
        cont_cam.add_widget(self.overlay)
        self._cont_cam = cont_cam
        self.lay.add_widget(cont_cam)

        # Botones
        botones = BoxLayout(orientation='vertical', size_hint=(1, 0.28),
                            padding=6, spacing=4)
        fila1 = BoxLayout(size_hint=(1, 0.5), spacing=4)
        self.b_def = Button(text='DEFINIR AREA', background_color=(0.3, 0.5, 0.8, 1))
        self.b_def.bind(on_press=self.toggle_definir)
        fila1.add_widget(self.b_def)
        b_ref = Button(text='CAPTURAR REF.', background_color=(0.3, 0.6, 0.4, 1))
        b_ref.bind(on_press=self.capturar_ref)
        fila1.add_widget(b_ref)
        self.b_ini = Button(text='INICIAR', background_color=COL_VERDE)
        self.b_ini.bind(on_press=self.toggle_conteo)
        fila1.add_widget(self.b_ini)
        botones.add_widget(fila1)

        fila2 = BoxLayout(size_hint=(1, 0.5), spacing=4)
        b_menos = Button(text='-1', background_color=(0.6, 0.3, 0.3, 1),
                         size_hint=(0.25, 1))
        b_menos.bind(on_press=lambda x: self.corregir(-1))
        fila2.add_widget(b_menos)
        b_mas = Button(text='+1', background_color=(0.3, 0.6, 0.4, 1),
                       size_hint=(0.25, 1))
        b_mas.bind(on_press=lambda x: self.corregir(1))
        fila2.add_widget(b_mas)
        b_cerrar = Button(text='CERRAR TURNO', background_color=COL_NARANJA,
                          size_hint=(0.5, 1))
        b_cerrar.bind(on_press=self.cerrar_turno)
        fila2.add_widget(b_cerrar)
        botones.add_widget(fila2)
        self.lay.add_widget(botones)

        # Bucle de conteo
        Clock.schedule_interval(self._tick, 1.0 / 10.0)
        # Tactil para definir ROI
        self._cont_cam.bind(on_touch_down=self._td, on_touch_move=self._tm,
                            on_touch_up=self._tu)

    # --- Geometria del ROI en pixeles de pantalla ---
    def roi_pantalla(self):
        w = self._cont_cam
        x = w.x + min(self.roi[0], self.roi[2]) * w.width
        y = w.y + (1 - max(self.roi[1], self.roi[3])) * w.height
        x2 = w.x + max(self.roi[0], self.roi[2]) * w.width
        y2 = w.y + (1 - min(self.roi[1], self.roi[3])) * w.height
        return x, y, x2, y2

    def _norm(self, tx, ty):
        w = self._cont_cam
        nx = (tx - w.x) / w.width
        ny = 1 - (ty - w.y) / w.height
        return max(0, min(1, nx)), max(0, min(1, ny))

    def _td(self, w, t):
        if self.definiendo and w.collide_point(*t.pos):
            nx, ny = self._norm(*t.pos)
            self.roi[0], self.roi[1] = nx, ny
            self.roi[2], self.roi[3] = nx, ny
            self._arr = True
            return True

    def _tm(self, w, t):
        if self._arr and self.definiendo:
            nx, ny = self._norm(*t.pos)
            self.roi[2], self.roi[3] = nx, ny
            return True

    def _tu(self, w, t):
        self._arr = False

    def toggle_definir(self, *a):
        self.definiendo = not self.definiendo
        self.b_def.text = 'ARRASTRA...' if self.definiendo else 'DEFINIR AREA'

    def _extraer_roi_gris(self):
        """Toma el frame actual de la camara y devuelve el ROI en gris (NumPy)."""
        if not isinstance(self.cam, Camera) or self.cam.texture is None:
            return None
        tex = self.cam.texture
        w, h = tex.size
        pixels = tex.pixels  # bytes RGBA
        arr = np.frombuffer(pixels, dtype=np.uint8).reshape(h, w, 4)
        # Recortar ROI
        x1 = int(min(self.roi[0], self.roi[2]) * w)
        x2 = int(max(self.roi[0], self.roi[2]) * w)
        y1 = int(min(self.roi[1], self.roi[3]) * h)
        y2 = int(max(self.roi[1], self.roi[3]) * h)
        if x2 - x1 < 5 or y2 - y1 < 5:
            return None
        roi = arr[y1:y2, x1:x2, :3]  # solo RGB
        return a_gris(roi)

    def capturar_ref(self, *a):
        gris = self._extraer_roi_gris()
        if gris is None:
            self.lbl_estado.text = 'Define un area valida primero'
            return
        self.contador.set_referencia(gris)
        self.definiendo = False
        self.b_def.text = 'DEFINIR AREA'
        self.lbl_estado.text = 'Referencia capturada OK'

    def toggle_conteo(self, *a):
        if self.contador.referencia is None:
            self.lbl_estado.text = 'Captura la referencia primero'
            return
        self.contando = not self.contando
        self.b_ini.text = 'PAUSAR' if self.contando else 'INICIAR'

    def corregir(self, d):
        self.contador.conteo = max(0, self.contador.conteo + d)
        self.lbl_conteo.text = '[b]%d[/b]' % self.contador.conteo

    def _tick(self, dt):
        if self.contando and self.contador.referencia is not None:
            gris = self._extraer_roi_gris()
            if gris is not None:
                self.contador.actualizar(gris)
        self.lbl_conteo.text = '[b]%d[/b]' % self.contador.conteo
        est = self.contador.estado if self.contador.referencia is not None else 'sin ref'
        self.lbl_estado.text = 'Estado: %s (%.0f%%)' % (
            est, self.contador.ultima_fraccion * 100)

    def cerrar_turno(self, *a):
        self.contando = False
        app = App.get_running_app()
        app.turno['total_balones'] = self.contador.conteo
        app.turno['hora_cierre'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.manager.current = 'cierre'


# ===========================================================================
# PANTALLA 3: CIERRE
# ===========================================================================
class PantallaCierre(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.lay = BoxLayout(orientation='vertical', padding=25, spacing=15)
        with self.canvas.before:
            Color(*COL_FONDO)
            self._r = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._u, size=self._u)

        self.lay.add_widget(Label(text='[b]CIERRE DE TURNO[/b]', markup=True,
                                  font_size='24sp', color=COL_NARANJA, size_hint=(1, 0.12)))
        self.lay.add_widget(Label(text='Nombre del operador que cierra:',
                                  color=COL_TEXTO, font_size='16sp', size_hint=(1, 0.08)))
        self.inp = TextInput(hint_text='Ej: Maria Lopez', multiline=False,
                             font_size='18sp', size_hint=(1, 0.1))
        self.lay.add_widget(self.inp)
        self.resumen = Label(text='', color=COL_TEXTO, font_size='16sp',
                             size_hint=(1, 0.45), markup=True)
        self.lay.add_widget(self.resumen)
        b = Button(text='GUARDAR REPORTE', font_size='18sp',
                   background_color=COL_NARANJA, size_hint=(1, 0.15))
        b.bind(on_press=self.guardar)
        self.lay.add_widget(b)
        self.add_widget(self.lay)

    def _u(self, *a):
        self._r.pos = self.pos
        self._r.size = self.size

    def on_enter(self):
        t = App.get_running_app().turno
        self.resumen.text = (
            '[b]RESUMEN[/b]\n\nApertura: %s\n%s\n\nCierre: %s\n\n'
            '[color=F08019][b]TOTAL BALONES: %d[/b][/color]' % (
                t.get('operador_apertura', '--'), t.get('hora_apertura', '--'),
                t.get('hora_cierre', '--'), t.get('total_balones', 0)))

    def guardar(self, *a):
        app = App.get_running_app()
        cierre = self.inp.text.strip() or '(no indicado)'
        app.turno['operador_cierre'] = cierre
        ruta = carpeta_datos()
        stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        with open(os.path.join(ruta, 'turno_%s.json' % stamp), 'w',
                  encoding='utf-8') as f:
            json.dump(app.turno, f, ensure_ascii=False, indent=2)
        csv_path = os.path.join(ruta, 'reporte_turnos.csv')
        nuevo = not os.path.exists(csv_path)
        with open(csv_path, 'a', encoding='utf-8') as f:
            if nuevo:
                f.write('operador_apertura,hora_apertura,operador_cierre,'
                        'hora_cierre,total_balones\n')
            f.write('%s,%s,%s,%s,%d\n' % (
                app.turno['operador_apertura'], app.turno['hora_apertura'],
                app.turno['operador_cierre'], app.turno['hora_cierre'],
                app.turno['total_balones']))
        self.resumen.text += '\n\n[color=4CAF50]Guardado OK[/color]'
        Clock.schedule_once(lambda dt: setattr(self.manager, 'current', 'apertura'), 2)


# ===========================================================================
# APP
# ===========================================================================
class ConteoApp(App):
    def build(self):
        self.turno = {}
        Window.clearcolor = COL_FONDO
        if platform == 'android':
            from android.permissions import request_permissions, Permission
            request_permissions([Permission.CAMERA,
                                 Permission.WRITE_EXTERNAL_STORAGE,
                                 Permission.READ_EXTERNAL_STORAGE])
        sm = ScreenManager()
        sm.add_widget(PantallaApertura(name='apertura'))
        sm.add_widget(PantallaConteo(name='conteo'))
        sm.add_widget(PantallaCierre(name='cierre'))
        return sm


if __name__ == '__main__':
    ConteoApp().run()
