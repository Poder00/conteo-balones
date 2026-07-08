# -*- coding: utf-8 -*-
"""
DETECTOR DE BALONES DE GLP - App Android v2 (Kivy + NumPy)
===========================================================
El celular cuenta los llenados de balones solo, con su propia camara.
Conteo con NumPy puro (sin OpenCV). Tema blanco con acentos azules.

Flujo de 3 pantallas:
  1. CONFIGURACION: tiempo de llenado (seg) + nombre del operador
  2. CAMARA: video vertical grande, area (ROI), botones por etapa
  3. REPORTE: resumen a pantalla completa + guardado

Mejoras v2:
  - Tema blanco / azul
  - Tiempo de llenado configurable desde la pantalla inicial
  - Camara VERTICAL que llena el ancho (arregla tamano, posicion y ROI)
  - Rotacion de imagen opcional (por si el sensor entrega de lado)
  - Botones que aparecen por etapa
  - Boton REGRESAR y PAUSAR
  - Reporte a pantalla completa
  - Sin botones -1 / +1, sin logo
"""

import os
import time
import datetime
import json

from kivy.app import App
from kivy.uix.screenmanager import ScreenManager, Screen, FadeTransition
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.camera import Camera
from kivy.uix.widget import Widget
from kivy.graphics import Color, Line, RoundedRectangle, Rectangle
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.utils import platform, get_color_from_hex
from kivy.metrics import dp

import numpy as np

# ===========================================================================
# CONFIGURACION POR DEFECTO
# ===========================================================================
UMBRAL_DIFERENCIA = 40          # 0-255: cuanto debe cambiar un pixel
PORCENTAJE_OCUPACION = 0.25     # fraccion del area que debe cambiar
SEGUNDOS_CONFIRMACION = 1.5
SEGUNDOS_VACIADO = 2.0

# --- ROTACION DE LA CAMARA ---
# Si la imagen sale de lado, cambia este valor: 0, 90, 180 o 270.
# En muchos celulares Android la camara trasera necesita 90 o 270.
ROTACION_CAMARA = 90

# --- Paleta (tema blanco / azul) ---
C_AZUL = get_color_from_hex("#185FA5")       # azul principal (botones)
C_AZUL_CLARO = get_color_from_hex("#378ADD")  # azul de resalte (ROI, contando)
C_AZUL_OSCURO = get_color_from_hex("#042C53")  # texto titulos
C_BLANCO = get_color_from_hex("#FFFFFF")
C_FONDO = get_color_from_hex("#F7F9FB")       # fondo general
C_GRIS_TEXTO = get_color_from_hex("#374151")
C_GRIS_SUAVE = get_color_from_hex("#9CA3AF")
C_BORDE = get_color_from_hex("#D1D5DB")
C_ROJO = get_color_from_hex("#E24B4A")

CARPETA = "conteo_balones_data"


def carpeta_datos():
    if platform == 'android':
        from android.storage import app_storage_path
        base = app_storage_path()
    else:
        base = os.path.expanduser('~')
    ruta = os.path.join(base, CARPETA)
    os.makedirs(ruta, exist_ok=True)
    return ruta


# ===========================================================================
# HELPERS NUMPY (reemplazo de OpenCV)
# ===========================================================================
def a_gris(rgb):
    r = rgb[:, :, 0].astype(np.float32)
    g = rgb[:, :, 1].astype(np.float32)
    b = rgb[:, :, 2].astype(np.float32)
    return (0.299 * r + 0.587 * g + 0.114 * b).astype(np.uint8)


def fraccion_diferente(ref, act, umbral):
    if ref.shape != act.shape:
        h = min(ref.shape[0], act.shape[0])
        w = min(ref.shape[1], act.shape[1])
        ref = ref[:h, :w]
        act = act[:h, :w]
    diff = np.abs(ref.astype(np.int16) - act.astype(np.int16))
    cambiados = np.count_nonzero(diff >= umbral)
    return float(cambiados) / diff.size if diff.size > 0 else 0.0


# ===========================================================================
# WIDGET BOTON REDONDEADO (bonito)
# ===========================================================================
class BotonBonito(Button):
    def __init__(self, color_fondo=None, color_texto=None, borde=None, **kwargs):
        super().__init__(**kwargs)
        self.background_normal = ''
        self.background_color = (0, 0, 0, 0)  # transparente, dibujamos nosotros
        self._cf = color_fondo if color_fondo else C_AZUL
        self._ct = color_texto if color_texto else C_BLANCO
        self._borde = borde  # (color, grosor) o None
        self.color = self._ct
        self.bold = True
        self.font_size = '16sp'
        self.bind(pos=self._draw, size=self._draw, state=self._draw)

    def _draw(self, *a):
        self.canvas.before.clear()
        with self.canvas.before:
            if self._borde:
                Color(*self._borde[0])
                RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(10)])
                Color(*C_BLANCO)
                g = self._borde[1]
                RoundedRectangle(pos=(self.pos[0] + g, self.pos[1] + g),
                                 size=(self.size[0] - 2 * g, self.size[1] - 2 * g),
                                 radius=[dp(9)])
                self.color = self._ct
            else:
                c = [min(1, x * 0.85) for x in self._cf[:3]] + [1] \
                    if self.state == 'down' else self._cf
                Color(*c)
                RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(10)])
                self.color = self._ct


def campo_texto(hint=''):
    ti = TextInput(hint_text=hint, multiline=False, font_size='17sp',
                   size_hint=(1, None), height=dp(48),
                   background_color=C_FONDO, foreground_color=C_AZUL_OSCURO,
                   cursor_color=C_AZUL, padding=[dp(14), dp(13)])
    return ti


# ===========================================================================
# MAQUINA DE ESTADOS
# ===========================================================================
class Contador:
    def __init__(self):
        self.referencia = None
        self.estado = 'VACIA'
        self.conteo = 0
        self.t_min = 15.0
        self.t_ocupacion = None
        self.t_llenado = None
        self.t_vaciado = None
        self.frac = 0.0

    def set_ref(self, gris):
        self.referencia = gris.copy()
        self.estado = 'VACIA'
        self.t_ocupacion = self.t_llenado = self.t_vaciado = None

    def actualizar(self, gris):
        if self.referencia is None:
            return False
        ahora = time.time()
        self.frac = fraccion_diferente(self.referencia, gris, UMBRAL_DIFERENCIA)
        ocupada = self.frac >= PORCENTAJE_OCUPACION

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
                    dur = ahora - self.t_llenado
                    conto = dur >= self.t_min
                    if conto:
                        self.conteo += 1
                    self.estado = 'VACIA'
                    self.t_ocupacion = self.t_llenado = self.t_vaciado = None
                    return conto
            else:
                self.t_vaciado = None
        return False


# ===========================================================================
# PANTALLA 1: CONFIGURACION
# ===========================================================================
class PantallaConfig(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        with self.canvas.before:
            Color(*C_BLANCO)
            self._bg = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._u, size=self._u)

        root = BoxLayout(orientation='vertical', padding=[dp(24), dp(30)],
                         spacing=dp(16))

        # Encabezado con icono
        head = BoxLayout(orientation='vertical', size_hint=(1, 0.32), spacing=dp(6))
        icono = Widget(size_hint=(1, 0.6))
        with icono.canvas:
            Color(*get_color_from_hex("#E6F1FB"))
            self._ic = RoundedRectangle(radius=[dp(14)])
        icono.bind(pos=lambda *a: self._pos_icono(icono),
                   size=lambda *a: self._pos_icono(icono))
        head.add_widget(icono)
        head.add_widget(Label(text='[b]Detector de Balones[/b]', markup=True,
                              font_size='22sp', color=C_AZUL_OSCURO,
                              size_hint=(1, 0.25)))
        head.add_widget(Label(text='Conteo automatico por turno',
                              font_size='13sp', color=C_GRIS_SUAVE,
                              size_hint=(1, 0.15)))
        root.add_widget(head)

        # Campo tiempo
        root.add_widget(Label(text='[b]Tiempo estimado de un llenado (seg)[/b]',
                              markup=True, halign='left', font_size='13sp',
                              color=C_GRIS_TEXTO, size_hint=(1, None), height=dp(20),
                              text_size=(Window.width - dp(48), None)))
        self.inp_tiempo = campo_texto('15')
        self.inp_tiempo.text = '15'
        self.inp_tiempo.input_filter = 'int'
        root.add_widget(self.inp_tiempo)

        # Campo operador
        root.add_widget(Label(text='[b]Operador que abre el turno[/b]',
                              markup=True, halign='left', font_size='13sp',
                              color=C_GRIS_TEXTO, size_hint=(1, None), height=dp(20),
                              text_size=(Window.width - dp(48), None)))
        self.inp_op = campo_texto('Ej: Juan Perez')
        root.add_widget(self.inp_op)

        self.msg = Label(text='', font_size='13sp', color=C_ROJO,
                         size_hint=(1, None), height=dp(24))
        root.add_widget(self.msg)

        root.add_widget(Widget())  # espaciador

        btn = BotonBonito(text='COMENZAR', color_fondo=C_AZUL,
                          size_hint=(1, None), height=dp(54))
        btn.bind(on_press=self.comenzar)
        root.add_widget(btn)

        self.add_widget(root)

    def _u(self, *a):
        self._bg.pos = self.pos
        self._bg.size = self.size

    def _pos_icono(self, w):
        lado = min(w.width, w.height, dp(60))
        self._ic.size = (lado, lado)
        self._ic.pos = (w.center_x - lado / 2, w.center_y - lado / 2)

    def comenzar(self, *a):
        op = self.inp_op.text.strip()
        if not op:
            self.msg.text = 'Ingrese el nombre del operador.'
            return
        try:
            t = int(self.inp_tiempo.text)
            if t <= 0:
                raise ValueError
        except ValueError:
            self.msg.text = 'Ingrese un tiempo valido en segundos.'
            return
        app = App.get_running_app()
        app.turno = {
            'operador_apertura': op,
            'hora_apertura': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }
        app.tiempo_llenado = t
        self.manager.current = 'camara'


# ===========================================================================
# PANTALLA 2: CAMARA
# ===========================================================================
class OverlayROI(Widget):
    def __init__(self, pantalla, **kwargs):
        super().__init__(**kwargs)
        self.p = pantalla
        Clock.schedule_interval(self._draw, 1.0 / 15.0)

    def _draw(self, dt):
        self.canvas.after.clear()
        x1, y1, x2, y2 = self.p.roi_en_pantalla()
        if x2 - x1 < 2:
            return
        with self.canvas.after:
            if self.p.contando:
                Color(*C_AZUL_CLARO)
            else:
                Color(*C_AZUL)
            Line(rectangle=(x1, y1, x2 - x1, y2 - y1), width=dp(1.4))


class PantallaCamara(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.contador = Contador()
        self.contando = False
        self.definiendo = False
        self.roi = [0.3, 0.3, 0.7, 0.7]   # fraccion (0-1)
        self._arr = False
        self.cam = None
        self.etapa = 'inicio'  # inicio -> area_lista -> ref_lista -> contando
        self._built = False

    def on_enter(self):
        if self._built:
            return
        self._built = True
        self.contador.t_min = App.get_running_app().tiempo_llenado

        with self.canvas.before:
            Color(*C_BLANCO)
            self._bg = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._u, size=self._u)

        root = BoxLayout(orientation='vertical')

        # --- Barra superior ---
        top = BoxLayout(size_hint=(1, None), height=dp(70), padding=[dp(16), dp(10)])
        with top.canvas.before:
            Color(*C_BLANCO)
            self._tb = Rectangle()
            Color(*get_color_from_hex("#EEF1F4"))
            self._tl = Rectangle()  # linea inferior
        top.bind(pos=self._top_bg, size=self._top_bg)
        self.lbl_conteo = Label(text='[b]0[/b]', markup=True, font_size='36sp',
                                color=C_AZUL, size_hint=(None, 1), width=dp(80),
                                halign='left', valign='middle')
        self.lbl_conteo.bind(size=lambda *a: setattr(
            self.lbl_conteo, 'text_size', self.lbl_conteo.size))
        top.add_widget(self.lbl_conteo)
        top.add_widget(Label(text='BALONES', font_size='10sp', color=C_GRIS_SUAVE,
                             size_hint=(None, 1), width=dp(60), halign='left',
                             valign='bottom'))
        self.lbl_estado = Label(text='Estado: --', font_size='12sp',
                                color=C_GRIS_TEXTO, halign='right', valign='middle')
        self.lbl_estado.bind(size=lambda *a: setattr(
            self.lbl_estado, 'text_size', self.lbl_estado.size))
        top.add_widget(self.lbl_estado)
        root.add_widget(top)

        # --- Camara (vertical, llena ancho) ---
        cam_box = FloatLayout(size_hint=(1, 1))
        try:
            # Resolucion VERTICAL para que coincida con el celular
            self.cam = Camera(play=True, resolution=(480, 640),
                              allow_stretch=True, keep_ratio=True)
        except Exception as e:
            self.cam = Label(text='No se pudo abrir la camara:\n%s' % e,
                             color=C_GRIS_TEXTO)
        self.cam.size_hint = (1, 1)
        cam_box.add_widget(self.cam)
        self.overlay = OverlayROI(self)
        self.overlay.size_hint = (1, 1)
        cam_box.add_widget(self.overlay)
        self._cam_box = cam_box
        cam_box.bind(on_touch_down=self._td, on_touch_move=self._tm,
                     on_touch_up=self._tu)
        root.add_widget(cam_box)

        # --- Panel de botones (cambia por etapa) ---
        self.panel = BoxLayout(orientation='vertical', size_hint=(1, None),
                               height=dp(150), padding=[dp(14), dp(10)],
                               spacing=dp(9))
        root.add_widget(self.panel)

        self.add_widget(root)
        self._rot = ROTACION_CAMARA
        Clock.schedule_interval(self._tick, 1.0 / 10.0)
        self._construir_botones()

    def _u(self, *a):
        self._bg.pos = self.pos
        self._bg.size = self.size

    def _top_bg(self, *a):
        t = self.children[0].children[-1] if self.children else None
        # dibuja fondo barra
        self._tb.pos = (0, Window.height - dp(70))
        self._tb.size = (Window.width, dp(70))
        self._tl.pos = (0, Window.height - dp(71))
        self._tl.size = (Window.width, dp(1))

    # ----- Botones por etapa -----
    def _construir_botones(self):
        self.panel.clear_widgets()

        # Texto de ayuda por etapa
        ayudas = {
            'inicio': 'Paso 1: define el area del tanque',
            'area_lista': 'Paso 2: con el area vacia, captura la referencia',
            'ref_lista': 'Paso 3: inicia el conteo',
            'contando': 'Contando... puedes pausar para ajustar',
        }
        self.panel.add_widget(Label(text=ayudas.get(self.etapa, ''),
                                    font_size='11sp', color=C_GRIS_SUAVE,
                                    size_hint=(1, None), height=dp(18)))

        # Boton principal segun etapa
        if self.etapa == 'inicio':
            b = BotonBonito(text='DEFINIR AREA' if not self.definiendo
                            else 'ARRASTRA EN EL VIDEO...', color_fondo=C_AZUL,
                            size_hint=(1, None), height=dp(50))
            b.bind(on_press=self.toggle_definir)
            self.panel.add_widget(b)
        elif self.etapa == 'area_lista':
            b = BotonBonito(text='CAPTURAR REFERENCIA', color_fondo=C_AZUL,
                            size_hint=(1, None), height=dp(50))
            b.bind(on_press=self.capturar_ref)
            self.panel.add_widget(b)
        elif self.etapa == 'ref_lista':
            b = BotonBonito(text='INICIAR CONTEO', color_fondo=C_AZUL,
                            size_hint=(1, None), height=dp(50))
            b.bind(on_press=self.iniciar)
            self.panel.add_widget(b)
        elif self.etapa == 'contando':
            b = BotonBonito(text='PAUSAR Y AJUSTAR', color_fondo=C_AZUL_CLARO,
                            size_hint=(1, None), height=dp(50))
            b.bind(on_press=self.pausar)
            self.panel.add_widget(b)

        # Fila inferior: REGRESAR + CERRAR TURNO
        fila = BoxLayout(size_hint=(1, None), height=dp(44), spacing=dp(8))
        b_reg = BotonBonito(text='REGRESAR', color_texto=C_GRIS_TEXTO,
                            borde=(C_BORDE, dp(1.5)), size_hint=(0.5, 1))
        b_reg.font_size = '13sp'
        b_reg.bind(on_press=self.regresar)
        fila.add_widget(b_reg)
        b_cer = BotonBonito(text='CERRAR TURNO', color_texto=get_color_from_hex("#A32D2D"),
                            borde=(C_ROJO, dp(1.5)), size_hint=(0.5, 1))
        b_cer.font_size = '13sp'
        b_cer.bind(on_press=self.cerrar_turno)
        fila.add_widget(b_cer)
        self.panel.add_widget(fila)

    # ----- Geometria del ROI (CORREGIDA para camara vertical) -----
    def _area_video(self):
        """Devuelve (x, y, w, h) reales del video dentro del cam_box,
        respetando la proporcion (keep_ratio) para que el ROI cuadre."""
        box = self._cam_box
        if not isinstance(self.cam, Camera) or self.cam.texture is None:
            return box.x, box.y, box.width, box.height
        tw, th = self.cam.texture.size
        if tw == 0 or th == 0:
            return box.x, box.y, box.width, box.height
        # Con rotacion 90/270 se intercambian ancho y alto
        if self._rot in (90, 270):
            tw, th = th, tw
        escala = min(box.width / tw, box.height / th)
        vw, vh = tw * escala, th * escala
        vx = box.x + (box.width - vw) / 2
        vy = box.y + (box.height - vh) / 2
        return vx, vy, vw, vh

    def roi_en_pantalla(self):
        vx, vy, vw, vh = self._area_video()
        x1 = vx + min(self.roi[0], self.roi[2]) * vw
        x2 = vx + max(self.roi[0], self.roi[2]) * vw
        y1 = vy + (1 - max(self.roi[1], self.roi[3])) * vh
        y2 = vy + (1 - min(self.roi[1], self.roi[3])) * vh
        return x1, y1, x2, y2

    def _norm(self, tx, ty):
        vx, vy, vw, vh = self._area_video()
        nx = (tx - vx) / vw if vw else 0
        ny = 1 - (ty - vy) / vh if vh else 0
        return max(0, min(1, nx)), max(0, min(1, ny))

    def _td(self, w, t):
        if self.definiendo and self._cam_box.collide_point(*t.pos):
            nx, ny = self._norm(*t.pos)
            self.roi = [nx, ny, nx, ny]
            self._arr = True
            return True

    def _tm(self, w, t):
        if self._arr and self.definiendo:
            nx, ny = self._norm(*t.pos)
            self.roi[2], self.roi[3] = nx, ny
            return True

    def _tu(self, w, t):
        if self._arr:
            self._arr = False
            # Al soltar, si el area es valida, pasa de etapa
            if abs(self.roi[2] - self.roi[0]) > 0.05 and \
               abs(self.roi[3] - self.roi[1]) > 0.05:
                self.definiendo = False
                self.etapa = 'area_lista'
                self._construir_botones()
            return True

    def toggle_definir(self, *a):
        self.definiendo = not self.definiendo
        self._construir_botones()

    # ----- Extraer ROI en gris (con rotacion) -----
    def _roi_gris(self):
        if not isinstance(self.cam, Camera) or self.cam.texture is None:
            return None
        tex = self.cam.texture
        w, h = tex.size
        arr = np.frombuffer(tex.pixels, dtype=np.uint8).reshape(h, w, 4)
        rgb = arr[:, :, :3]
        # Aplicar rotacion si hace falta
        if self._rot == 90:
            rgb = np.rot90(rgb, k=1)
        elif self._rot == 180:
            rgb = np.rot90(rgb, k=2)
        elif self._rot == 270:
            rgb = np.rot90(rgb, k=3)
        H, W = rgb.shape[:2]
        x1 = int(min(self.roi[0], self.roi[2]) * W)
        x2 = int(max(self.roi[0], self.roi[2]) * W)
        y1 = int(min(self.roi[1], self.roi[3]) * H)
        y2 = int(max(self.roi[1], self.roi[3]) * H)
        if x2 - x1 < 5 or y2 - y1 < 5:
            return None
        return a_gris(rgb[y1:y2, x1:x2])

    def capturar_ref(self, *a):
        g = self._roi_gris()
        if g is None:
            self.lbl_estado.text = 'Area invalida'
            return
        self.contador.set_ref(g)
        self.etapa = 'ref_lista'
        self._construir_botones()

    def iniciar(self, *a):
        if self.contador.referencia is None:
            return
        self.contando = True
        self.etapa = 'contando'
        self._construir_botones()

    def pausar(self, *a):
        self.contando = False
        self.etapa = 'ref_lista'
        self._construir_botones()

    def regresar(self, *a):
        # Retrocede una etapa
        if self.etapa == 'contando':
            self.contando = False
            self.etapa = 'ref_lista'
        elif self.etapa == 'ref_lista':
            self.contador.referencia = None
            self.etapa = 'area_lista'
        elif self.etapa == 'area_lista':
            self.etapa = 'inicio'
            self.definiendo = False
        else:  # inicio -> volver a configuracion
            self.manager.current = 'config'
            return
        self._construir_botones()

    def _tick(self, dt):
        if self.contando and self.contador.referencia is not None:
            g = self._roi_gris()
            if g is not None:
                self.contador.actualizar(g)
        self.lbl_conteo.text = '[b]%d[/b]' % self.contador.conteo
        est = self.contador.estado if self.contador.referencia is not None else 'sin ref'
        self.lbl_estado.text = 'Estado: %s\n%.0f%%' % (est, self.contador.frac * 100)

    def cerrar_turno(self, *a):
        self.contando = False
        app = App.get_running_app()
        app.turno['total_balones'] = self.contador.conteo
        app.turno['hora_cierre'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.manager.current = 'reporte'


# ===========================================================================
# PANTALLA 3: REPORTE (pantalla completa)
# ===========================================================================
class PantallaReporte(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        with self.canvas.before:
            Color(*C_BLANCO)
            self._bg = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._u, size=self._u)
        self.root = BoxLayout(orientation='vertical', padding=[dp(24), dp(34)],
                              spacing=dp(14))
        self.add_widget(self.root)

    def _u(self, *a):
        self._bg.pos = self.pos
        self._bg.size = self.size

    def on_enter(self):
        self.root.clear_widgets()
        t = App.get_running_app().turno

        # Icono check
        icono = Widget(size_hint=(1, 0.16))
        with icono.canvas:
            Color(*get_color_from_hex("#E6F1FB"))
            self._ic = RoundedRectangle(radius=[dp(30)])
        icono.bind(pos=lambda *a: self._pos_ic(icono),
                   size=lambda *a: self._pos_ic(icono))
        self.root.add_widget(icono)

        self.root.add_widget(Label(text='[b]Turno cerrado[/b]', markup=True,
                                   font_size='22sp', color=C_AZUL_OSCURO,
                                   size_hint=(1, None), height=dp(30)))
        self.root.add_widget(Label(text='Reporte guardado correctamente',
                                   font_size='13sp', color=C_GRIS_SUAVE,
                                   size_hint=(1, None), height=dp(20)))

        # Tarjeta resumen
        card = BoxLayout(orientation='vertical', size_hint=(1, 0.5),
                         padding=[dp(18), dp(16)], spacing=dp(4))
        with card.canvas.before:
            Color(*C_FONDO)
            self._cardbg = RoundedRectangle(radius=[dp(12)])
        card.bind(pos=lambda *a: self._card_bg(card),
                  size=lambda *a: self._card_bg(card))

        def fila(k, v):
            f = BoxLayout(size_hint=(1, None), height=dp(34))
            f.add_widget(Label(text=k, font_size='12sp', color=C_GRIS_SUAVE,
                               halign='left', valign='middle',
                               text_size=(dp(120), None)))
            f.add_widget(Label(text=v, markup=True, font_size='12sp',
                               color=get_color_from_hex("#111827"), halign='right',
                               valign='middle', text_size=(dp(170), None)))
            return f

        card.add_widget(fila('Apertura', '[b]%s[/b]\n%s' % (
            t.get('operador_apertura', '--'),
            t.get('hora_apertura', '--')[-8:])))
        card.add_widget(fila('Cierre', '[b]%s[/b]\n%s' % (
            t.get('operador_cierre', '--'),
            t.get('hora_cierre', '--')[-8:])))

        card.add_widget(Label(text='TOTAL DE BALONES', font_size='11sp',
                              color=C_GRIS_SUAVE, size_hint=(1, None), height=dp(20)))
        card.add_widget(Label(text='[b]%d[/b]' % t.get('total_balones', 0),
                              markup=True, font_size='52sp', color=C_AZUL,
                              size_hint=(1, None), height=dp(64)))
        self.root.add_widget(card)

        self.root.add_widget(Widget())

        btn = BotonBonito(text='NUEVO TURNO', color_fondo=C_AZUL,
                          size_hint=(1, None), height=dp(54))
        btn.bind(on_press=self.nuevo)
        self.root.add_widget(btn)

        self._guardar(t)

    def _pos_ic(self, w):
        lado = min(w.width, w.height, dp(56))
        self._ic.size = (lado, lado)
        self._ic.pos = (w.center_x - lado / 2, w.center_y - lado / 2)

    def _card_bg(self, c):
        self._cardbg.pos = c.pos
        self._cardbg.size = c.size

    def _guardar(self, t):
        if t.get('_guardado'):
            return
        cierre_op = t.get('operador_cierre', '(no indicado)')
        ruta = carpeta_datos()
        stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        try:
            with open(os.path.join(ruta, 'turno_%s.json' % stamp), 'w',
                      encoding='utf-8') as f:
                json.dump(t, f, ensure_ascii=False, indent=2)
            csv_path = os.path.join(ruta, 'reporte_turnos.csv')
            nuevo = not os.path.exists(csv_path)
            with open(csv_path, 'a', encoding='utf-8') as f:
                if nuevo:
                    f.write('operador_apertura,hora_apertura,operador_cierre,'
                            'hora_cierre,total_balones\n')
                f.write('%s,%s,%s,%s,%d\n' % (
                    t.get('operador_apertura', ''), t.get('hora_apertura', ''),
                    cierre_op, t.get('hora_cierre', ''),
                    t.get('total_balones', 0)))
            t['_guardado'] = True
        except Exception as e:
            print("Error guardando:", e)

    def nuevo(self, *a):
        App.get_running_app().turno = {}
        self.manager.current = 'config'


# ===========================================================================
# APP
# ===========================================================================
class DetectorApp(App):
    def build(self):
        self.turno = {}
        self.tiempo_llenado = 15
        Window.clearcolor = C_BLANCO
        if platform == 'android':
            from android.permissions import request_permissions, Permission
            request_permissions([Permission.CAMERA,
                                 Permission.WRITE_EXTERNAL_STORAGE,
                                 Permission.READ_EXTERNAL_STORAGE])
        sm = ScreenManager(transition=FadeTransition(duration=0.2))
        sm.add_widget(PantallaConfig(name='config'))
        sm.add_widget(PantallaCamara(name='camara'))
        sm.add_widget(PantallaReporte(name='reporte'))
        return sm


if __name__ == '__main__':
    DetectorApp().run()
