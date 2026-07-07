# -*- coding: utf-8 -*-
"""
CONTEO DE BALONES DE GLP - Control por Turno
==============================================
App nativa Android (Kivy + OpenCV) para conteo automatico de llenados
de balones de gas, con apertura y cierre de turno.

Flujo:
  1. Apertura de turno (nombre operador) + foto de referencia del area vacia
  2. Definir area de conteo (ROI) sobre el video en vivo
  3. Iniciar conteo -> maquina de estados detecta llenados automaticamente
  4. Cierre de turno (nombre) -> resumen en pantalla + guardado del reporte

Maquina de estados por balanza:
  VACIA -> CONFIRMANDO -> LLENANDO -> (conteo +1) -> VACIA
"""

import os
import time
import datetime
import json

from kivy.app import App
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.image import Image
from kivy.graphics.texture import Texture
from kivy.graphics import Color, Line, Rectangle
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.utils import platform

import numpy as np
import cv2

# ---------------------------------------------------------------------------
# CONFIGURACION
# ---------------------------------------------------------------------------
# Umbral de diferencia respecto a la referencia (0-255). Mas alto = menos sensible.
UMBRAL_DIFERENCIA = 40
# Porcentaje del area (ROI) que debe cambiar para considerar "ocupada".
PORCENTAJE_OCUPACION = 0.25
# Segundos que debe mantenerse ocupada antes de confirmar (anti falso-positivo).
SEGUNDOS_CONFIRMACION = 1.5
# Tiempo minimo de llenado (s) - calibrar al ~70% del ciclo real mas rapido.
T_MINIMO_LLENADO_S = 15.0
# Segundos de "vacia" continua para resetear a estado VACIA tras un llenado.
SEGUNDOS_VACIADO = 2.0

# Colores de marca (charcoal / naranja)
COL_FONDO = (0.239, 0.263, 0.286, 1)   # #3D4349
COL_NARANJA = (0.941, 0.502, 0.098, 1)  # #F08019
COL_TEXTO = (0.95, 0.95, 0.95, 1)


def carpeta_datos():
    """Devuelve una carpeta escribible segun la plataforma."""
    if platform == 'android':
        from android.storage import app_storage_path
        base = app_storage_path()
    else:
        base = os.path.expanduser('~')
    ruta = os.path.join(base, 'conteo_balones_data')
    os.makedirs(ruta, exist_ok=True)
    return ruta


# ---------------------------------------------------------------------------
# MAQUINA DE ESTADOS DE CONTEO
# ---------------------------------------------------------------------------
class ContadorLlenado:
    """Maquina de estados que cuenta llenados comparando el ROI actual
    contra una imagen de referencia del area vacia."""

    def __init__(self):
        self.referencia_gris = None      # ROI de referencia en escala de grises
        self.estado = 'VACIA'
        self.conteo = 0
        self.t_inicio_ocupacion = None   # cuando empezo a estar ocupada
        self.t_inicio_llenado = None     # cuando se confirmo el llenado
        self.t_inicio_vaciado = None     # cuando empezo a estar vacia de nuevo

    def set_referencia(self, roi_gris):
        self.referencia_gris = cv2.GaussianBlur(roi_gris, (11, 11), 0)
        self.reset()

    def reset(self):
        self.estado = 'VACIA'
        self.conteo = 0
        self.t_inicio_ocupacion = None
        self.t_inicio_llenado = None
        self.t_inicio_vaciado = None

    def _fraccion_ocupada(self, roi_gris):
        """Fraccion del ROI que difiere de la referencia."""
        if self.referencia_gris is None:
            return 0.0
        roi_blur = cv2.GaussianBlur(roi_gris, (11, 11), 0)
        # Ajuste de tamano por si el ROI cambia de dimension
        if roi_blur.shape != self.referencia_gris.shape:
            roi_blur = cv2.resize(roi_blur, (self.referencia_gris.shape[1],
                                             self.referencia_gris.shape[0]))
        diff = cv2.absdiff(self.referencia_gris, roi_blur)
        _, thresh = cv2.threshold(diff, UMBRAL_DIFERENCIA, 255, cv2.THRESH_BINARY)
        return float(np.count_nonzero(thresh)) / thresh.size

    def actualizar(self, roi_gris):
        """Procesa un frame y avanza la maquina de estados.
        Devuelve dict con estado, conteo y fraccion, para la UI."""
        ahora = time.time()
        frac = self._fraccion_ocupada(roi_gris)
        ocupada = frac >= PORCENTAJE_OCUPACION

        if self.estado == 'VACIA':
            if ocupada:
                if self.t_inicio_ocupacion is None:
                    self.t_inicio_ocupacion = ahora
                elif ahora - self.t_inicio_ocupacion >= SEGUNDOS_CONFIRMACION:
                    self.estado = 'CONFIRMANDO'
            else:
                self.t_inicio_ocupacion = None

        elif self.estado == 'CONFIRMANDO':
            if ocupada:
                # Confirmado: comienza el llenado
                self.estado = 'LLENANDO'
                self.t_inicio_llenado = ahora
            else:
                self.estado = 'VACIA'
                self.t_inicio_ocupacion = None

        elif self.estado == 'LLENANDO':
            if not ocupada:
                if self.t_inicio_vaciado is None:
                    self.t_inicio_vaciado = ahora
                elif ahora - self.t_inicio_vaciado >= SEGUNDOS_VACIADO:
                    # Se retiro el balon. Contar solo si duro lo minimo.
                    duracion = ahora - self.t_inicio_llenado
                    if duracion >= T_MINIMO_LLENADO_S:
                        self.conteo += 1
                    self.estado = 'VACIA'
                    self.t_inicio_ocupacion = None
                    self.t_inicio_llenado = None
                    self.t_inicio_vaciado = None
            else:
                self.t_inicio_vaciado = None

        return {'estado': self.estado, 'conteo': self.conteo, 'fraccion': frac}


# ---------------------------------------------------------------------------
# WIDGET DE CAMARA CON ROI
# ---------------------------------------------------------------------------
class VistaCamara(Image):
    """Muestra el video de la camara y permite dibujar el ROI arrastrando.
    Corre el contador cuando esta activo."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.capture = None
        self.contador = ContadorLlenado()
        self.contando = False
        self.definiendo_roi = False
        # ROI en coordenadas normalizadas (0-1) respecto al frame
        self.roi = [0.3, 0.3, 0.7, 0.7]  # x1,y1,x2,y2
        self._arrastrando = False
        self._frame_actual = None
        self.callback_estado = None  # funcion para reportar estado a la UI
        self._ev = None

    def iniciar_camara(self):
        if self.capture is None:
            self.capture = cv2.VideoCapture(0)
            self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        if self._ev is None:
            self._ev = Clock.schedule_interval(self.update, 1.0 / 15.0)

    def detener_camara(self):
        if self._ev is not None:
            self._ev.cancel()
            self._ev = None
        if self.capture is not None:
            self.capture.release()
            self.capture = None

    def capturar_referencia(self):
        """Toma el ROI actual como imagen de referencia del area vacia."""
        if self._frame_actual is None:
            return False
        roi_bgr = self._recortar_roi(self._frame_actual)
        if roi_bgr is None or roi_bgr.size == 0:
            return False
        gris = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY)
        self.contador.set_referencia(gris)
        return True

    def _recortar_roi(self, frame):
        h, w = frame.shape[:2]
        x1 = int(min(self.roi[0], self.roi[2]) * w)
        y1 = int(min(self.roi[1], self.roi[3]) * h)
        x2 = int(max(self.roi[0], self.roi[2]) * w)
        y2 = int(max(self.roi[1], self.roi[3]) * h)
        if x2 - x1 < 5 or y2 - y1 < 5:
            return None
        return frame[y1:y2, x1:x2]

    def update(self, dt):
        if self.capture is None:
            return
        ret, frame = self.capture.read()
        if not ret:
            return
        self._frame_actual = frame.copy()

        # Correr el contador si esta activo
        if self.contando and self.contador.referencia_gris is not None:
            roi_bgr = self._recortar_roi(frame)
            if roi_bgr is not None and roi_bgr.size > 0:
                gris = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY)
                info = self.contador.actualizar(gris)
                if self.callback_estado:
                    self.callback_estado(info)

        # Dibujar el rectangulo del ROI sobre el frame
        h, w = frame.shape[:2]
        x1 = int(min(self.roi[0], self.roi[2]) * w)
        y1 = int(min(self.roi[1], self.roi[3]) * h)
        x2 = int(max(self.roi[0], self.roi[2]) * w)
        y2 = int(max(self.roi[1], self.roi[3]) * h)
        color = (25, 128, 240)  # naranja en BGR
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 3)

        # Convertir a textura de Kivy
        buf = cv2.flip(frame, 0).tobytes()
        texture = Texture.create(size=(w, h), colorfmt='bgr')
        texture.blit_buffer(buf, colorfmt='bgr', bufferfmt='ubyte')
        self.texture = texture

    # --- Definir ROI arrastrando el dedo ---
    def on_touch_down(self, touch):
        if self.definiendo_roi and self.collide_point(*touch.pos):
            nx, ny = self._normalizar(touch.pos)
            self.roi[0], self.roi[1] = nx, ny
            self.roi[2], self.roi[3] = nx, ny
            self._arrastrando = True
            return True
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        if self._arrastrando and self.definiendo_roi:
            nx, ny = self._normalizar(touch.pos)
            self.roi[2], self.roi[3] = nx, ny
            return True
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        if self._arrastrando:
            self._arrastrando = False
            return True
        return super().on_touch_up(touch)

    def _normalizar(self, pos):
        """Convierte coordenadas de pantalla a normalizadas (0-1) del frame.
        Nota: el eje Y se invierte porque el frame se voltea al mostrar."""
        x = (pos[0] - self.x) / self.width
        y = 1.0 - (pos[1] - self.y) / self.height
        x = max(0.0, min(1.0, x))
        y = max(0.0, min(1.0, y))
        return x, y


# ---------------------------------------------------------------------------
# PANTALLA 1: APERTURA DE TURNO
# ---------------------------------------------------------------------------
class PantallaApertura(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        layout = BoxLayout(orientation='vertical', padding=30, spacing=20)

        with self.canvas.before:
            Color(*COL_FONDO)
            self._rect = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._upd_rect, size=self._upd_rect)

        titulo = Label(text='[b]APERTURA DE TURNO[/b]', markup=True,
                       font_size='26sp', color=COL_NARANJA,
                       size_hint=(1, 0.2))
        layout.add_widget(titulo)

        layout.add_widget(Label(text='Nombre del operador que abre:',
                                color=COL_TEXTO, font_size='18sp',
                                size_hint=(1, 0.1)))

        self.input_nombre = TextInput(hint_text='Ej: Juan Perez',
                                      multiline=False, font_size='20sp',
                                      size_hint=(1, 0.15))
        layout.add_widget(self.input_nombre)

        self.lbl_info = Label(text='', color=COL_TEXTO, font_size='15sp',
                              size_hint=(1, 0.25))
        layout.add_widget(self.lbl_info)

        btn = Button(text='INICIAR TURNO', font_size='22sp',
                     background_color=COL_NARANJA, size_hint=(1, 0.2))
        btn.bind(on_press=self.iniciar)
        layout.add_widget(btn)

        self.add_widget(layout)

    def _upd_rect(self, *a):
        self._rect.pos = self.pos
        self._rect.size = self.size

    def iniciar(self, *a):
        nombre = self.input_nombre.text.strip()
        if not nombre:
            self.lbl_info.text = 'Ingrese el nombre del operador.'
            return
        app = App.get_running_app()
        app.turno = {
            'operador_apertura': nombre,
            'hora_apertura': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }
        self.manager.current = 'referencia'


# ---------------------------------------------------------------------------
# PANTALLA 2: REFERENCIA + DEFINIR AREA
# ---------------------------------------------------------------------------
class PantallaReferencia(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        layout = BoxLayout(orientation='vertical', padding=10, spacing=8)

        self.instruccion = Label(
            text='[b]1)[/b] Enfoque el area VACIA  [b]2)[/b] Toque "DEFINIR AREA" y '
                 'arrastre el recuadro  [b]3)[/b] "CAPTURAR REFERENCIA"',
            markup=True, color=COL_TEXTO, font_size='14sp', size_hint=(1, 0.12))
        layout.add_widget(self.instruccion)

        self.vista = VistaCamara(size_hint=(1, 0.68))
        layout.add_widget(self.vista)

        botones = BoxLayout(orientation='horizontal', size_hint=(1, 0.1), spacing=8)
        self.btn_definir = Button(text='DEFINIR AREA', font_size='15sp',
                                  background_color=(0.3, 0.5, 0.8, 1))
        self.btn_definir.bind(on_press=self.toggle_definir)
        botones.add_widget(self.btn_definir)

        btn_ref = Button(text='CAPTURAR REFERENCIA', font_size='15sp',
                         background_color=(0.3, 0.6, 0.4, 1))
        btn_ref.bind(on_press=self.capturar)
        botones.add_widget(btn_ref)
        layout.add_widget(botones)

        self.lbl_estado = Label(text='Area sin definir.', color=COL_TEXTO,
                                font_size='14sp', size_hint=(1, 0.06))
        layout.add_widget(self.lbl_estado)

        btn_ok = Button(text='CONTINUAR AL CONTEO', font_size='18sp',
                        background_color=COL_NARANJA, size_hint=(1, 0.12))
        btn_ok.bind(on_press=self.continuar)
        layout.add_widget(btn_ok)

        self.add_widget(layout)
        self.referencia_ok = False

    def on_enter(self):
        self.vista.iniciar_camara()

    def toggle_definir(self, *a):
        self.vista.definiendo_roi = not self.vista.definiendo_roi
        if self.vista.definiendo_roi:
            self.btn_definir.text = 'ARRASTRANDO...'
            self.lbl_estado.text = 'Arrastre el dedo sobre el area del tanque.'
        else:
            self.btn_definir.text = 'DEFINIR AREA'

    def capturar(self, *a):
        if self.vista.capturar_referencia():
            self.referencia_ok = True
            self.vista.definiendo_roi = False
            self.btn_definir.text = 'DEFINIR AREA'
            self.lbl_estado.text = '[color=00cc44]Referencia capturada OK.[/color]'
            self.lbl_estado.markup = True
        else:
            self.lbl_estado.text = 'No se pudo capturar. Revise el area.'

    def continuar(self, *a):
        if not self.referencia_ok:
            self.lbl_estado.text = 'Primero capture la referencia del area vacia.'
            return
        # Pasar la vista de camara a la pantalla de conteo (misma instancia)
        app = App.get_running_app()
        app.vista_camara = self.vista
        self.remove_widget(self.vista.parent if False else self.vista) \
            if self.vista.parent is None else None
        self.manager.current = 'conteo'


# ---------------------------------------------------------------------------
# PANTALLA 3: CONTEO EN VIVO
# ---------------------------------------------------------------------------
class PantallaConteo(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.layout = BoxLayout(orientation='vertical', padding=10, spacing=8)

        self.lbl_conteo = Label(text='[b]0[/b]', markup=True, font_size='72sp',
                                color=COL_NARANJA, size_hint=(1, 0.25))
        self.layout.add_widget(self.lbl_conteo)

        self.lbl_estado = Label(text='Estado: --', color=COL_TEXTO,
                                font_size='18sp', size_hint=(1, 0.08))
        self.layout.add_widget(self.lbl_estado)

        self.cont_camara = BoxLayout(size_hint=(1, 0.45))
        self.layout.add_widget(self.cont_camara)

        botones = BoxLayout(orientation='horizontal', size_hint=(1, 0.12), spacing=8)
        self.btn_iniciar = Button(text='COMENZAR CONTEO', font_size='18sp',
                                  background_color=(0.3, 0.6, 0.4, 1))
        self.btn_iniciar.bind(on_press=self.toggle_conteo)
        botones.add_widget(self.btn_iniciar)

        btn_menos = Button(text='-1 (corregir)', font_size='16sp',
                           background_color=(0.6, 0.3, 0.3, 1), size_hint=(0.5, 1))
        btn_menos.bind(on_press=self.restar)
        botones.add_widget(btn_menos)
        self.layout.add_widget(botones)

        btn_cerrar = Button(text='CERRAR TURNO', font_size='20sp',
                            background_color=COL_NARANJA, size_hint=(1, 0.12))
        btn_cerrar.bind(on_press=self.cerrar_turno)
        self.layout.add_widget(btn_cerrar)

        self.add_widget(self.layout)

    def on_enter(self):
        app = App.get_running_app()
        self.vista = app.vista_camara
        if self.vista.parent:
            self.vista.parent.remove_widget(self.vista)
        self.vista.size_hint = (1, 1)
        self.cont_camara.add_widget(self.vista)
        self.vista.definiendo_roi = False
        self.vista.callback_estado = self.actualizar_estado
        self.vista.iniciar_camara()

    def actualizar_estado(self, info):
        self.lbl_conteo.text = '[b]%d[/b]' % info['conteo']
        self.lbl_estado.text = 'Estado: %s   (ocupacion %.0f%%)' % (
            info['estado'], info['fraccion'] * 100)

    def toggle_conteo(self, *a):
        self.vista.contando = not self.vista.contando
        if self.vista.contando:
            self.btn_iniciar.text = 'PAUSAR CONTEO'
            self.btn_iniciar.background_color = (0.7, 0.5, 0.2, 1)
        else:
            self.btn_iniciar.text = 'COMENZAR CONTEO'
            self.btn_iniciar.background_color = (0.3, 0.6, 0.4, 1)

    def restar(self, *a):
        if self.vista.contador.conteo > 0:
            self.vista.contador.conteo -= 1
            self.lbl_conteo.text = '[b]%d[/b]' % self.vista.contador.conteo

    def cerrar_turno(self, *a):
        self.vista.contando = False
        self.manager.current = 'cierre'


# ---------------------------------------------------------------------------
# PANTALLA 4: CIERRE DE TURNO + RESUMEN
# ---------------------------------------------------------------------------
class PantallaCierre(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.layout = BoxLayout(orientation='vertical', padding=25, spacing=15)

        with self.canvas.before:
            Color(*COL_FONDO)
            self._rect = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._upd, size=self._upd)

        self.layout.add_widget(Label(text='[b]CIERRE DE TURNO[/b]', markup=True,
                                     font_size='24sp', color=COL_NARANJA,
                                     size_hint=(1, 0.12)))

        self.layout.add_widget(Label(text='Nombre del operador que cierra:',
                                     color=COL_TEXTO, font_size='16sp',
                                     size_hint=(1, 0.08)))
        self.input_cierre = TextInput(hint_text='Ej: Maria Lopez',
                                      multiline=False, font_size='18sp',
                                      size_hint=(1, 0.1))
        self.layout.add_widget(self.input_cierre)

        self.lbl_resumen = Label(text='', color=COL_TEXTO, font_size='16sp',
                                 size_hint=(1, 0.4), halign='left', valign='top',
                                 markup=True)
        self.lbl_resumen.bind(size=self._ajustar_texto)
        self.layout.add_widget(self.lbl_resumen)

        btn = Button(text='GUARDAR Y GENERAR REPORTE', font_size='18sp',
                     background_color=COL_NARANJA, size_hint=(1, 0.15))
        btn.bind(on_press=self.guardar)
        self.layout.add_widget(btn)

        self.add_widget(self.layout)

    def _upd(self, *a):
        self._rect.pos = self.pos
        self._rect.size = self.size

    def _ajustar_texto(self, *a):
        self.lbl_resumen.text_size = (self.lbl_resumen.width, None)

    def on_enter(self):
        app = App.get_running_app()
        total = app.vista_camara.contador.conteo
        app.turno['total_balones'] = total
        app.turno['hora_cierre'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self._mostrar_resumen(app.turno)

    def _mostrar_resumen(self, t):
        self.lbl_resumen.text = (
            '[b]RESUMEN DEL TURNO[/b]\n\n'
            'Operador apertura: %s\n'
            'Hora apertura: %s\n\n'
            'Hora cierre: %s\n\n'
            '[color=F08019][b]TOTAL BALONES: %d[/b][/color]' % (
                t.get('operador_apertura', '--'),
                t.get('hora_apertura', '--'),
                t.get('hora_cierre', '--'),
                t.get('total_balones', 0)))

    def guardar(self, *a):
        app = App.get_running_app()
        cierre = self.input_cierre.text.strip()
        if not cierre:
            cierre = '(no indicado)'
        app.turno['operador_cierre'] = cierre

        # Guardar en JSON (historial) y CSV
        ruta = carpeta_datos()
        stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')

        # JSON individual del turno
        with open(os.path.join(ruta, 'turno_%s.json' % stamp), 'w',
                  encoding='utf-8') as f:
            json.dump(app.turno, f, ensure_ascii=False, indent=2)

        # Anexar a CSV maestro
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

        self.lbl_resumen.text += '\n\n[color=00cc44]Reporte guardado en:\n%s[/color]' % ruta

        # Detener camara y volver al inicio
        Clock.schedule_once(self._finalizar, 3)

    def _finalizar(self, dt):
        app = App.get_running_app()
        app.vista_camara.detener_camara()
        self.manager.current = 'apertura'


# ---------------------------------------------------------------------------
# APP PRINCIPAL
# ---------------------------------------------------------------------------
class ConteoApp(App):
    def build(self):
        self.turno = {}
        self.vista_camara = None
        Window.clearcolor = COL_FONDO

        # Permisos en Android
        if platform == 'android':
            from android.permissions import request_permissions, Permission
            request_permissions([
                Permission.CAMERA,
                Permission.WRITE_EXTERNAL_STORAGE,
                Permission.READ_EXTERNAL_STORAGE,
            ])

        sm = ScreenManager()
        sm.add_widget(PantallaApertura(name='apertura'))
        sm.add_widget(PantallaReferencia(name='referencia'))
        sm.add_widget(PantallaConteo(name='conteo'))
        sm.add_widget(PantallaCierre(name='cierre'))
        return sm


if __name__ == '__main__':
    ConteoApp().run()
