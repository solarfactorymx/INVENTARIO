import os
import sys
import json
import hashlib
import shutil
from datetime import datetime, timedelta
import tkinter as tk
import customtkinter as ctk
from PIL import Image, ImageTk
from tkinter import messagebox, filedialog
import pandas as pd
import platform
import ctypes
import urllib.request
import email.utils

# Librerías para Firebase
import firebase_admin
from firebase_admin import credentials, db

# Intentamos importar fitz (PyMuPDF)
try:
    import fitz
    EXISTE_FITZ = True
except ImportError:
    EXISTE_FITZ = False

def ruta_recurso(nombre_archivo):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, nombre_archivo)

def encriptar_password(password):
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

def ocultar_archivo_local(ruta):
    if os.path.exists(ruta):
        try:
            if platform.system() == "Windows":
                ctypes.windll.kernel32.SetFileAttributesW(str(os.path.abspath(ruta)), 0x80)
                ctypes.windll.kernel32.SetFileAttributesW(str(os.path.abspath(ruta)), 0x02)
        except Exception:
            pass

# =========================================================================
# GESTOR DE PERSISTENCIA SEGURA Y SEMÁFORO DE SINCRONIZACIÓN
# =========================================================================

URL_FIREBASE = 'https://produccion-led-mexico-default-rtdb.firebaseio.com'
ARCHIVO_CACHE_LOCAL = "produccion_local_cache.json"
ARCHIVO_SESION = "sesion_activa.json"
CAMBIOS_LOCALES_PENDIENTES = False

def verificar_conexion():
    try:
        urllib.request.urlopen("http://clients3.google.com/generate_204", timeout=2)
        return True
    except:
        return False

def inicializar_firebase():
    try:
        if not firebase_admin._apps:
            ruta_credenciales = ruta_recurso("credenciales.json")
            if os.path.exists(ruta_credenciales):
                with open(ruta_credenciales, "r", encoding="utf-8") as f:
                    cred_dict = json.load(f)

                cred = credentials.Certificate(cred_dict)
                firebase_admin.initialize_app(cred, {'databaseURL': URL_FIREBASE})
                print("✅ Conectado a Firebase exitosamente.")
                return True
    except Exception as e:
        print("⚠️ Modo Offline operativo (Sin conexión a Firebase).", e)
    return False

inicializar_firebase()

def cargar_cache_local():
    if os.path.exists(ARCHIVO_CACHE_LOCAL):
        try:
            with open(ARCHIVO_CACHE_LOCAL, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {"trabajos_activos": [], "historial_terminados": [], "modelos": {}, "tema": "Dark"}

def guardar_cache_local(datos):
    try:
        if platform.system() == "Windows" and os.path.exists(ARCHIVO_CACHE_LOCAL):
            ctypes.windll.kernel32.SetFileAttributesW(str(os.path.abspath(ARCHIVO_CACHE_LOCAL)), 0x80)
        with open(ARCHIVO_CACHE_LOCAL, "w", encoding="utf-8") as f:
            json.dump(datos, f, indent=4, ensure_ascii=False)
        ocultar_archivo_local(ARCHIVO_CACHE_LOCAL)
    except Exception as e:
        print("Error guardando caché local:", e)

# Configuración estética global adaptativa
ctk.set_appearance_mode(cargar_cache_local().get("tema", "Dark"))
ctk.set_default_color_theme("blue")

# --- AUTENTICACIÓN SEGURA Y SESIÓN ---
def leer_usuarios_nube():
    if not firebase_admin._apps or not verificar_conexion():
        raise ConnectionError("Se requiere conexión a internet para validar el acceso de usuarios.")
    datos = db.reference('usuarios').get()
    if datos is None:
        usuarios_iniciales = {
            "admin": {"password": encriptar_password("1234"), "nombre": "Administrador General", "rol": "Admin"}
        }
        db.reference('usuarios').set(usuarios_iniciales)
        return usuarios_iniciales
    return datos

def guardar_usuarios_nube(data):
    if firebase_admin._apps and verificar_conexion():
        db.reference('usuarios').set(data)
    else:
        raise ConnectionError("Se requiere internet para modificar usuarios en el sistema.")

def leer_sesion():
    if os.path.exists(ARCHIVO_SESION):
        try:
            with open(ARCHIVO_SESION, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return None
    return None

def guardar_sesion(username, recordar, info_user=None):
    if recordar:
        data = {"username": username}
        if info_user: data["info"] = info_user
        if platform.system() == "Windows" and os.path.exists(ARCHIVO_SESION):
            ctypes.windll.kernel32.SetFileAttributesW(str(os.path.abspath(ARCHIVO_SESION)), 0x80)
        with open(ARCHIVO_SESION, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
        ocultar_archivo_local(ARCHIVO_SESION)
    else:
        borrar_sesion()

def borrar_sesion():
    if os.path.exists(ARCHIVO_SESION):
        try:
            if platform.system() == "Windows":
                ctypes.windll.kernel32.SetFileAttributesW(str(os.path.abspath(ARCHIVO_SESION)), 0x80)
            os.remove(ARCHIVO_SESION)
        except:
            pass

# --- GESTIÓN DINÁMICA DE MODELOS ---
MODELOS_DEFAULT = {
    "B-GOLF": {"imagen": "B-GOLF.png", "pdf": "B-GOLF.PDF"},
    "PEPE-400": {"imagen": "PEPE-400.PNG", "pdf": "plano_pepe_400.pdf"},
    "REMOLQUE": {"imagen": "REMOLQUE.PNG", "pdf": "REMOLQUE.pdf"},
    "ESTRUCTURA SPS-4": {"imagen": "SPS-4.PNG", "pdf": "plano_sps4.pdf"},
    "RACK2": {"imagen": "RACK.PNG", "pdf": "RACK.PDF"}
}

global CATALOGO_MODELOS, CATALOGO_IMAGENES, CATALOGO_PLANOS_PDF
CATALOGO_MODELOS = {}
CATALOGO_IMAGENES = {}
CATALOGO_PLANOS_PDF = {}

def sincronizar_diccionarios_globales():
    global CATALOGO_IMAGENES, CATALOGO_PLANOS_PDF
    CATALOGO_IMAGENES.clear()
    CATALOGO_PLANOS_PDF.clear()
    for k, v in CATALOGO_MODELOS.items():
        CATALOGO_IMAGENES[k] = v.get("imagen", "")
        CATALOGO_PLANOS_PDF[k] = v.get("pdf", "")

def leer_modelos_nube():
    if firebase_admin._apps and verificar_conexion():
        try:
            datos = db.reference('modelos').get()
            if datos is not None:
                cache = cargar_cache_local()
                cache["modelos"] = datos
                guardar_cache_local(cache)
                return datos
        except Exception:
            pass
    return cargar_cache_local().get("modelos", MODELOS_DEFAULT)

def guardar_modelos_nube(data):
    global CATALOGO_MODELOS, CAMBIOS_LOCALES_PENDIENTES
    CATALOGO_MODELOS = data
    cache = cargar_cache_local()
    cache["modelos"] = data
    guardar_cache_local(cache)
    CAMBIOS_LOCALES_PENDIENTES = True
    if firebase_admin._apps and verificar_conexion():
        try:
            db.reference('modelos').set(data)
            CAMBIOS_LOCALES_PENDIENTES = False
        except Exception:
            pass

CATALOGO_MODELOS = leer_modelos_nube()
sincronizar_diccionarios_globales()

def obtener_ruta_archivo_modelo(filename):
    if not filename: return ""
    local_dir = os.path.abspath("archivos_modelos")
    local_path = os.path.join(local_dir, filename)
    if os.path.exists(local_path):
        return local_path
    recurso_path = ruta_recurso(os.path.join("assets", filename))
    if os.path.exists(recurso_path):
        return recurso_path
    return ""

def guardar_archivo_modelo_local(filepath):
    if not filepath or not os.path.exists(filepath): return ""
    filename = os.path.basename(filepath)
    local_dir = os.path.abspath("archivos_modelos")
    os.makedirs(local_dir, exist_ok=True)
    dest_path = os.path.join(local_dir, filename)
    if filepath != dest_path:
        shutil.copy(filepath, dest_path)
    return filename

# --- TRABAJOS Y PRODUCCIÓN ---
def leer_trabajos_activos():
    if firebase_admin._apps and verificar_conexion():
        try:
            datos = db.reference('trabajos_activos').get()
            if datos is not None:
                cache = cargar_cache_local()
                cache["trabajos_activos"] = datos
                guardar_cache_local(cache)
                return datos
        except Exception:
            pass
    return cargar_cache_local().get("trabajos_activos", [])

def guardar_trabajos_activos(data):
    global DB_TRABAJOS_ANTERIORES, DB_TRABAJOS_TERMINADOS, CAMBIOS_LOCALES_PENDIENTES
    DB_TRABAJOS_ANTERIORES = data
    cache = cargar_cache_local()
    cache["trabajos_activos"] = data
    guardar_cache_local(cache)
    CAMBIOS_LOCALES_PENDIENTES = True
    if firebase_admin._apps and verificar_conexion():
        try:
            db.reference('trabajos_activos').set(data)
            db.reference('historial_terminados').set(DB_TRABAJOS_TERMINADOS)
            CAMBIOS_LOCALES_PENDIENTES = False
        except Exception:
            pass

def leer_historial_terminados():
    if firebase_admin._apps and verificar_conexion():
        try:
            datos = db.reference('historial_terminados').get()
            if datos is not None:
                cache = cargar_cache_local()
                cache["historial_terminados"] = datos
                guardar_cache_local(cache)
                return datos
        except Exception:
            pass
    return cargar_cache_local().get("historial_terminados", [])

def guardar_historial_terminados(data):
    global DB_TRABAJOS_ANTERIORES, DB_TRABAJOS_TERMINADOS, CAMBIOS_LOCALES_PENDIENTES
    DB_TRABAJOS_TERMINADOS = data
    cache = cargar_cache_local()
    cache["historial_terminados"] = data
    guardar_cache_local(cache)
    CAMBIOS_LOCALES_PENDIENTES = True
    if firebase_admin._apps and verificar_conexion():
        try:
            db.reference('trabajos_activos').set(DB_TRABAJOS_ANTERIORES)
            db.reference('historial_terminados').set(data)
            CAMBIOS_LOCALES_PENDIENTES = False
        except Exception:
            pass

def obtener_fecha_internet():
    try:
        req = urllib.request.Request("https://google.com", method="HEAD")
        with urllib.request.urlopen(req, timeout=2) as response:
            fecha_str = response.headers['Date']
            tupla_fecha = email.utils.parsedate_tz(fecha_str)
            timestamp = email.utils.mktime_tz(tupla_fecha)
            return datetime.fromtimestamp(timestamp)
    except Exception:
        return datetime.now()

class ToolTip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tw = None
        self.widget.bind("<Enter>", self.enter)
        self.widget.bind("<Leave>", self.leave)

    def enter(self, event=None):
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + 25
        self.tw = tk.Toplevel(self.widget)
        self.tw.wm_overrideredirect(True)
        self.tw.wm_geometry(f"+{x}+{y}")
        self.tw.attributes("-topmost", True)
        
        # Colores dinámicos para el Tooltip
        bg_color = "#F8F9F9" if ctk.get_appearance_mode() == "Light" else "#1E272E"
        fg_color = "#17202A" if ctk.get_appearance_mode() == "Light" else "#FFFFFF"
        
        label = tk.Label(self.tw, text=self.text, justify='left',
                         background=bg_color, foreground=fg_color,
                         relief='solid', borderwidth=1, font=("Arial", 11, "normal"), padx=10, pady=5)
        label.pack(ipadx=1)

    def leave(self, event=None):
        if self.tw:
            self.tw.destroy()
            self.tw = None

global DB_TRABAJOS_ANTERIORES, DB_TRABAJOS_TERMINADOS
DB_TRABAJOS_ANTERIORES = leer_trabajos_activos()
DB_TRABAJOS_TERMINADOS = leer_historial_terminados()

class FilaNuevaOrden(ctk.CTkFrame):
    def __init__(self, master, usuario_por_defecto, al_cambiar_modelo, abrir_plano_callback, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.usuario_por_defecto = usuario_por_defecto
        self.abrir_plano_callback = abrir_plano_callback

        self.grid_columnconfigure((0, 1, 2, 3, 4, 5), weight=1)
        self.grid_columnconfigure((6, 7), weight=0)

        fuente_titulos = ctk.CTkFont(size=10, weight="bold")
        ctk.CTkLabel(self, text="Cantidad Piezas", font=fuente_titulos, text_color=("gray40", "gray70")).grid(row=0, column=0, padx=4, sticky="w")
        ctk.CTkLabel(self, text="Urgentes", font=fuente_titulos, text_color=("#C0392B", "#E74C3C")).grid(row=0, column=1, padx=4, sticky="w")
        ctk.CTkLabel(self, text="Modelo", font=fuente_titulos, text_color=("gray40", "gray70")).grid(row=0, column=2, padx=4, sticky="w")
        ctk.CTkLabel(self, text="Observaciones", font=fuente_titulos, text_color=("gray40", "gray70")).grid(row=0, column=3, padx=4, sticky="w")
        ctk.CTkLabel(self, text="Solicitante", font=fuente_titulos, text_color=("#2980B9", "#3498DB")).grid(row=0, column=4, padx=4, sticky="w")
        ctk.CTkLabel(self, text="Prioridad", font=fuente_titulos, text_color=("gray40", "gray70")).grid(row=0, column=5, padx=4, sticky="w")
        ctk.CTkLabel(self, text="Preview", font=fuente_titulos, text_color=("gray40", "gray70")).grid(row=0, column=6, padx=4)
        ctk.CTkLabel(self, text="Plano", font=fuente_titulos, text_color=("gray40", "gray70")).grid(row=0, column=7, padx=4)

        self.ent_cant = ctk.CTkEntry(self, width=50, justify="center")
        self.ent_cant.grid(row=1, column=0, padx=4, pady=(0, 8), sticky="ew")
        self.ent_cant.insert(0, "1")

        self.ent_urgentes = ctk.CTkEntry(self, width=50, justify="center")
        self.ent_urgentes.grid(row=1, column=1, padx=4, pady=(0, 8), sticky="ew")
        self.ent_urgentes.insert(0, "0")

        self.combo_modelo = ctk.CTkComboBox(self, values=list(CATALOGO_MODELOS.keys()) if CATALOGO_MODELOS else [""],
                                            command=lambda val: al_cambiar_modelo(val, widget_fila=self))
        self.combo_modelo.grid(row=1, column=2, padx=4, pady=(0, 8), sticky="ew")

        self.ent_obs = ctk.CTkEntry(self, placeholder_text="Observaciones...")
        self.ent_obs.grid(row=1, column=3, padx=4, pady=(0, 8), sticky="ew")

        self.ent_solicitante = ctk.CTkEntry(self, placeholder_text=self.usuario_por_defecto, justify="center")
        self.ent_solicitante.grid(row=1, column=4, padx=4, pady=(0, 8), sticky="ew")

        self.combo_prioridad = ctk.CTkOptionMenu(self, values=["1 (Urgente)", "2 (Normal)", "3 (Baja)"], width=90,
                                                 fg_color=("#E5E7E9", "#34495E"), button_color=("#D5D8DC", "#2C3E50"), text_color=("black", "white"))
        self.combo_prioridad.set("2 (Normal)")
        self.combo_prioridad.grid(row=1, column=5, padx=4, pady=(0, 8), sticky="ew")

        self.lbl_preview = ctk.CTkLabel(self, text="Sin", width=38, height=38, fg_color=("gray85", "gray20"), corner_radius=6, text_color=("black", "white"))
        self.lbl_preview.grid(row=1, column=6, padx=4, pady=(0, 8))

        self.btn_plano = ctk.CTkButton(self, text="📐 Plano", width=50, height=30,
                                       font=ctk.CTkFont(size=10, weight="bold"), fg_color="#8E44AD",
                                       hover_color="#7D3C98", text_color="white",
                                       command=lambda: self.abrir_plano_callback(self.combo_modelo.get()))
        self.btn_plano.grid(row=1, column=7, padx=4, pady=(0, 8))

        al_cambiar_modelo(self.combo_modelo.get(), widget_fila=self)

    def obtener_datos(self):
        solic = self.ent_solicitante.get().strip()
        if not solic: solic = self.usuario_por_defecto
        return {
            "cantidad": int(self.ent_cant.get() if self.ent_cant.get().isdigit() else 1),
            "urgentes": int(self.ent_urgentes.get() if self.ent_urgentes.get().isdigit() else 0),
            "modelo": self.combo_modelo.get(),
            "obs": self.ent_obs.get(),
            "solicitante": solic,
            "prioridad": self.combo_prioridad.get()[0]
        }

class VentanaLogin(ctk.CTk):
    def __init__(self, callback_exito):
        super().__init__()
        self.callback_exito = callback_exito
        self.title("LED MEXICO - Iniciar Sesión Segura")
        self.geometry("400+380+250")
        self.resizable(False, False)
        self.attributes("-topmost", True)

        ctk.CTkLabel(self, text="🔐 Acceso Corporativo", font=ctk.CTkFont(size=18, weight="bold"), text_color=("#2980B9", "#3498DB")).pack(pady=(25, 10))
        ctk.CTkLabel(self, text="Requiere conexión a internet para autenticación", font=ctk.CTkFont(size=11), text_color=("gray40", "gray70")).pack(pady=(0, 20))

        self.ent_user = ctk.CTkEntry(self, placeholder_text="Usuario", width=280, height=38, justify="center")
        self.ent_user.pack(pady=8)
        self.ent_user.focus()

        self.ent_pass = ctk.CTkEntry(self, placeholder_text="Contraseña", width=280, height=38, justify="center", show="*")
        self.ent_pass.pack(pady=8)
        self.ent_pass.bind("<Return>", lambda e: self.intentar_login())

        self.chk_recordar = ctk.CTkCheckBox(self, text="Mantener sesión activa", font=ctk.CTkFont(size=11))
        self.chk_recordar.pack(pady=10)
        self.chk_recordar.select()

        btn_entrar = ctk.CTkButton(self, text="ENTRAR", width=280, height=38, fg_color="#27AE60", hover_color="#1E8449",
                                   font=ctk.CTkFont(weight="bold"), text_color="white", command=self.intentar_login)
        btn_entrar.pack(pady=15)

    def intentar_login(self):
        user = self.ent_user.get().strip().lower()
        password = self.ent_pass.get().strip()
        if not user or not password:
            return messagebox.showerror("Campos vacíos", "Ingrese usuario y contraseña.", parent=self)
        try:
            usuarios = leer_usuarios_nube()
            if user in usuarios and usuarios[user]["password"] == encriptar_password(password):
                guardar_sesion(user, self.chk_recordar.get(), usuarios[user])
                self.destroy()
                self.callback_exito(user)
            else:
                messagebox.showerror("Error de Acceso", "Usuario o contraseña incorrectos.", parent=self)
        except Exception as e:
            messagebox.showerror("Sin Conexión", "Se requiere conexión obligatoria a internet para iniciar sesión.\n\nVerifique su red.", parent=self)

class AppControlProduccion(ctk.CTk):
    def __init__(self, usuario_actual):
        super().__init__()
        self.usuario_actual = usuario_actual
        sesion_local = leer_sesion()
        fallback_info = {"nombre": usuario_actual, "rol": "Taller"}
        if sesion_local and sesion_local.get("username") == usuario_actual and "info" in sesion_local:
            fallback_info = sesion_local["info"]
        try:
            usuarios_remotos = leer_usuarios_nube()
            self.info_usuario = usuarios_remotos.get(usuario_actual, fallback_info)
            guardar_sesion(usuario_actual, True, self.info_usuario)
        except:
            self.info_usuario = fallback_info

        self.rol_actual = self.info_usuario.get("rol", "Taller")
        if self.rol_actual == "Operador": self.rol_actual = "Taller"

        self.title(f"LED MEXICO - Control de Producción | Conectado: {self.info_usuario['nombre']} ({self.rol_actual})")
        self.pagina_actual_term = 0
        self.elementos_por_pagina = 50
        self.filtro_folio_busqueda = ""

        ancho_pantalla = self.winfo_screenwidth()
        alto_pantalla = self.winfo_screenheight()
        ancho_ventana = int(ancho_pantalla * 0.85)
        alto_ventana = int(alto_pantalla * 0.85)
        pos_x = (ancho_pantalla - ancho_ventana) // 2
        pos_y = max(0, (alto_pantalla - alto_ventana) // 2 - 30)

        self.geometry(f"{ancho_ventana}x{alto_ventana}+{pos_x}+{pos_y}")
        self.minsize(1200, 680)

        self.nuevas_filas = []
        self.referencias_dashboard = {}
        self.contador_folio = len(DB_TRABAJOS_ANTERIORES) + len(DB_TRABAJOS_TERMINADOS) + 1

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.scroll_principal = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll_principal.grid(row=0, column=0, sticky="nsew", padx=15, pady=10)
        self.scroll_principal.grid_columnconfigure(0, weight=1)

        self.disenar_encabezado()
        if self.rol_actual in ["Admin", "Inventarios"]:
            self.disenar_seccion_solicitud()
            self.disenar_seccion_nuevas_ordenes()
        self.disenar_seccion_dashboard()
        self.disenar_seccion_historial_terminados()

        self.after(8000, self.sincronizacion_automatica)
        self._resize_job = None
        self.bind("<Configure>", self.forzar_redibujado_en_resize)

    def sincronizacion_automatica(self):
        global DB_TRABAJOS_ANTERIORES, DB_TRABAJOS_TERMINADOS, CAMBIOS_LOCALES_PENDIENTES, CATALOGO_MODELOS
        if firebase_admin._apps and verificar_conexion():
            try:
                if CAMBIOS_LOCALES_PENDIENTES:
                    db.reference('trabajos_activos').set(DB_TRABAJOS_ANTERIORES)
                    db.reference('historial_terminados').set(DB_TRABAJOS_TERMINADOS)
                    db.reference('modelos').set(CATALOGO_MODELOS)
                    CAMBIOS_LOCALES_PENDIENTES = False
                else:
                    nube_activos = db.reference('trabajos_activos').get()
                    nube_historial = db.reference('historial_terminados').get()
                    nube_modelos = db.reference('modelos').get()

                    actualizado = False
                    if nube_activos is not None and json.dumps(DB_TRABAJOS_ANTERIORES, sort_keys=True) != json.dumps(nube_activos, sort_keys=True):
                        DB_TRABAJOS_ANTERIORES = nube_activos
                        actualizado = True
                        self.refrescar_dashboard_completo()

                    if nube_historial is not None and json.dumps(DB_TRABAJOS_TERMINADOS, sort_keys=True) != json.dumps(nube_historial, sort_keys=True):
                        DB_TRABAJOS_TERMINADOS = nube_historial
                        actualizado = True
                        self.actualizar_tabla_terminados_visual()

                    if nube_modelos is not None and json.dumps(CATALOGO_MODELOS, sort_keys=True) != json.dumps(nube_modelos, sort_keys=True):
                        CATALOGO_MODELOS = nube_modelos
                        sincronizar_diccionarios_globales()
                        self.actualizar_combobox_modelos()
                        actualizado = True

                    if actualizado:
                        cache = cargar_cache_local()
                        cache["trabajos_activos"] = DB_TRABAJOS_ANTERIORES
                        cache["historial_terminados"] = DB_TRABAJOS_TERMINADOS
                        cache["modelos"] = CATALOGO_MODELOS
                        guardar_cache_local(cache)
            except Exception:
                pass
        self.after(8000, self.sincronizacion_automatica)

    def forzar_redibujado_en_resize(self, event=None):
        if event is not None and event.widget is not self: return
        if self._resize_job: self.after_cancel(self._resize_job)
        self._resize_job = self.after(80, self._refrescar_layout_diferido)

    def _refrescar_layout_diferido(self):
        self._resize_job = None
        self.update_idletasks()

    def refrescar_dashboard_completo(self):
        for widget in self.tabla_frame.winfo_children():
            info = widget.grid_info()
            if info and int(info.get("row", 0)) > 0: widget.destroy()
        self.referencias_dashboard.clear()
        for datos in DB_TRABAJOS_ANTERIORES:
            self.inyectar_fila_en_dashboard(datos)

    def centrar_ventana_modal(self, modal, ancho_m, alto_m):
        modal.update_idletasks()
        w_screen = modal.winfo_screenwidth()
        h_screen = modal.winfo_screenheight()
        x = (w_screen - ancho_m) // 2
        y = max(0, (h_screen - alto_m) // 2 - 30)
        modal.geometry(f"{ancho_m}x{alto_m}+{x}+{y}")

    def alternar_tema(self):
        cache = cargar_cache_local()
        tema_actual = cache.get("tema", "Dark")
        
        if tema_actual == "Dark":
            nuevo_tema = "Light"
            self.btn_tema.configure(text="🌙 Oscuro")
        else:
            nuevo_tema = "Dark"
            self.btn_tema.configure(text="☀️ Claro")
            
        ctk.set_appearance_mode(nuevo_tema)
        cache["tema"] = nuevo_tema
        guardar_cache_local(cache)

    def cerrar_sesion(self):
        if messagebox.askyesno("Cerrar Sesión", "¿Desea cerrar la sesión actual?\n(Para volver a entrar requerirá internet)", parent=self):
            borrar_sesion()
            self.destroy()
            app_login = VentanaLogin(lambda u: AppControlProduccion(u).mainloop())
            app_login.mainloop()

    # --- EXPORTAR EXCEL ---
    def exportar_historial_excel(self):
        if not DB_TRABAJOS_TERMINADOS:
            return messagebox.showwarning("Sin Datos", "No hay registros en el historial de terminados para exportar.", parent=self)

        archivo_salida = filedialog.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Archivos de Excel", "*.xlsx")],
                                                      title="Guardar Historial", initialfile=f"Historial_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx")
        if not archivo_salida: return
        try:
            lista_general, lista_detalles = [], []
            for reg in DB_TRABAJOS_TERMINADOS:
                folio = reg.get("folio", "N/A")
                modelo = reg.get("modelo", "N/A")
                cantidad = reg.get("cantidad", 0)
                lista_general.append({
                    "Folio": folio, "Modelo": modelo, "Cantidad Total": cantidad,
                    "Estatus": reg.get("estatus", "N/A"), "Fecha Inicio": reg.get("fecha_inicio", "N/A"),
                    "Fecha Límite": reg.get("fecha_limite", "N/A"), "Fecha Entrega/Cierre": reg.get("fecha_entrega", "N/A"),
                    "Solicitante": reg.get("solicitante", "N/A"), "Entregó": reg.get("entrego", "N/A"),
                    "Recibió": reg.get("recibio", "N/A"), "Motivo Cancelación": reg.get("motivo_cancelacion", "")
                })
                parcialidades = reg.get("historial_parcialidades", reg.get("historial_entregas", []))
                if not parcialidades:
                    lista_detalles.append({
                        "Folio": folio, "Modelo": modelo, "N° Aviso": 1, "Fecha de Aviso": reg.get("fecha_entrega", "N/A"),
                        "Persona que Reportó": reg.get("entrego", "N/A"), "Material Disponible (Pzas)": cantidad,
                        "Observaciones": "Cierre directo sin avisos parciales previos"
                    })
                else:
                    for i, p in enumerate(parcialidades, start=1):
                        lista_detalles.append({
                            "Folio": folio, "Modelo": modelo, "N° Aviso": i, "Fecha de Aviso": p.get("fecha", "N/A"),
                            "Persona que Reportó": p.get("persona", "N/A"), "Material Disponible (Pzas)": p.get("cantidad", 0),
                            "Observaciones": p.get("observaciones", p.get("nota", ""))
                        })
            with pd.ExcelWriter(archivo_salida, engine="openpyxl") as writer:
                pd.DataFrame(lista_general).to_excel(writer, sheet_name="Historial General", index=False)
                pd.DataFrame(lista_detalles).to_excel(writer, sheet_name="Detalle de Material Disponible", index=False)
            messagebox.showinfo("Exportación Exitosa", f"El historial se ha exportado correctamente a:\n{archivo_salida}", parent=self)
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo generar Excel:\n{e}", parent=self)

    # --- MODALES DE GESTIÓN (USUARIOS Y MODELOS) ---
    def abrir_modal_gestion_usuarios(self):
        try:
            usrs_dict = leer_usuarios_nube()
        except:
            return messagebox.showerror("Sin Conexión", "Requiere conexión a internet por seguridad.", parent=self)
        modal = ctk.CTkToplevel(self)
        modal.title("Gestión de Usuarios (Nube)")
        self.centrar_ventana_modal(modal, 560, 640)
        modal.attributes("-topmost", True)
        modal.grab_set()

        ctk.CTkLabel(modal, text="👥 Administrar Cuentas Corporativas", font=ctk.CTkFont(size=13, weight="bold"), text_color=("#2980B9", "#3498DB")).pack(pady=10)
        frame_form = ctk.CTkFrame(modal, fg_color=("gray90", "gray15"))
        frame_form.pack(fill="x", padx=15, pady=5)
        ctk.CTkLabel(frame_form, text="Nuevo Usuario (ID sin espacios):", font=ctk.CTkFont(size=11), text_color=("black", "white")).pack(anchor="w", padx=10, pady=(6, 2))
        ent_nuevo_id = ctk.CTkEntry(frame_form)
        ent_nuevo_id.pack(fill="x", padx=10, pady=2)
        ctk.CTkLabel(frame_form, text="Nombre Completo:", font=ctk.CTkFont(size=11), text_color=("black", "white")).pack(anchor="w", padx=10, pady=(6, 2))
        ent_nuevo_nom = ctk.CTkEntry(frame_form)
        ent_nuevo_nom.pack(fill="x", padx=10, pady=2)
        ctk.CTkLabel(frame_form, text="Contraseña:", font=ctk.CTkFont(size=11), text_color=("black", "white")).pack(anchor="w", padx=10, pady=(6, 2))
        ent_nuevo_pass = ctk.CTkEntry(frame_form, show="*")
        ent_nuevo_pass.pack(fill="x", padx=10, pady=2)
        ctk.CTkLabel(frame_form, text="Rol del Sistema:", font=ctk.CTkFont(size=11), text_color=("black", "white")).pack(anchor="w", padx=10, pady=(6, 2))
        combo_rol = ctk.CTkOptionMenu(frame_form, values=["Taller", "Inventarios", "Admin"])
        combo_rol.set("Taller")
        combo_rol.pack(fill="x", padx=10, pady=(2, 10))

        ctk.CTkLabel(modal, text="Usuarios Registrados:", font=ctk.CTkFont(size=11, weight="bold"), text_color=("gray40", "gray70")).pack(anchor="w", padx=18, pady=(10, 2))
        scroll_usrs = ctk.CTkScrollableFrame(modal, height=140, fg_color=("gray85", "gray20"), corner_radius=6)
        scroll_usrs.pack(fill="both", expand=True, padx=18, pady=2)

        def actualizar_lista_usuarios_visual():
            for widget in scroll_usrs.winfo_children(): widget.destroy()
            try:
                actuales = leer_usuarios_nube()
                for u_id, u_info in actuales.items():
                    row_u = ctk.CTkFrame(scroll_usrs, fg_color="transparent")
                    row_u.pack(fill="x", pady=2)
                    txt_info = f"👤 {u_id} | {u_info['nombre']} ({u_info['rol']})"
                    ctk.CTkLabel(row_u, text=txt_info, font=ctk.CTkFont(size=11), text_color=("black", "white")).pack(side="left", padx=4)
                    if u_id != "admin":
                        ctk.CTkButton(row_u, text="✕", width=24, height=22, fg_color="#C0392B", hover_color="#922B21", text_color="white",
                                      command=lambda usr=u_id: eliminar_usuario_accion(usr)).pack(side="right", padx=4)
            except: pass

        def eliminar_usuario_accion(usr_id):
            if messagebox.askyesno("Confirmar", f"¿Eliminar usuario '{usr_id}'?", parent=modal):
                try:
                    actuales = leer_usuarios_nube()
                    if usr_id in actuales:
                        del actuales[usr_id]
                        guardar_usuarios_nube(actuales)
                        actualizar_lista_usuarios_visual()
                except Exception as e: messagebox.showerror("Error", str(e), parent=modal)

        def registrar_usuario():
            uid = ent_nuevo_id.get().strip().lower()
            nombre = ent_nuevo_nom.get().strip()
            pwd = ent_nuevo_pass.get().strip()
            if not uid or not nombre or not pwd: return messagebox.showerror("Error", "Todos obligatorios.", parent=modal)
            try:
                actuales = leer_usuarios_nube()
                if uid in actuales: return messagebox.showerror("Duplicado", f"'{uid}' ya existe.", parent=modal)
                actuales[uid] = {"password": encriptar_password(pwd), "nombre": nombre, "rol": combo_rol.get()}
                guardar_usuarios_nube(actuales)
                ent_nuevo_id.delete(0, "end"); ent_nuevo_nom.delete(0, "end"); ent_nuevo_pass.delete(0, "end")
                actualizar_lista_usuarios_visual()
            except Exception as e: messagebox.showerror("Error", str(e), parent=modal)

        ctk.CTkButton(modal, text="➕ Crear Nuevo Usuario", fg_color="#27AE60", hover_color="#1E8449", text_color="white", height=32, command=registrar_usuario).pack(fill="x", padx=15, pady=8)
        actualizar_lista_usuarios_visual()

    def abrir_modal_gestion_modelos(self):
        modal = ctk.CTkToplevel(self)
        modal.title("Gestión de Modelos")
        self.centrar_ventana_modal(modal, 600, 600)
        modal.attributes("-topmost", True)
        modal.grab_set()

        ctk.CTkLabel(modal, text="🛠️ Administrar Modelos de Producción", font=ctk.CTkFont(size=13, weight="bold"), text_color=("#2980B9", "#3498DB")).pack(pady=10)

        frame_form = ctk.CTkFrame(modal, fg_color=("gray90", "gray15"))
        frame_form.pack(fill="x", padx=15, pady=5)

        ruta_img = tk.StringVar(value="")
        ruta_pdf = tk.StringVar(value="")
        modo_edicion = tk.StringVar(value="")

        ctk.CTkLabel(frame_form, text="Nombre del Modelo:", font=ctk.CTkFont(size=11), text_color=("black", "white")).grid(row=0, column=0, padx=10, pady=5, sticky="w")
        ent_nombre = ctk.CTkEntry(frame_form, placeholder_text="Ej. NUEVO-MOD-01", width=300)
        ent_nombre.grid(row=0, column=1, padx=10, pady=5, sticky="ew")

        def seleccionar_archivo_modal(tipo, var_ruta, btn):
            if tipo == "img":
                path = filedialog.askopenfilename(filetypes=[("Imágenes", "*.png;*.jpg;*.jpeg;*.bmp")])
            else:
                path = filedialog.askopenfilename(filetypes=[("PDF", "*.pdf")])
            if path:
                var_ruta.set(path)
                btn.configure(text=os.path.basename(path), fg_color="#27AE60", text_color="white")

        btn_img = ctk.CTkButton(frame_form, text="Seleccionar Foto (Opc)", text_color="white", command=lambda: seleccionar_archivo_modal("img", ruta_img, btn_img))
        btn_img.grid(row=1, column=0, padx=10, pady=5)

        btn_pdf = ctk.CTkButton(frame_form, text="Seleccionar Plano (Opc)", text_color="white", command=lambda: seleccionar_archivo_modal("pdf", ruta_pdf, btn_pdf))
        btn_pdf.grid(row=1, column=1, padx=10, pady=5)

        def guardar_modelo_action():
            nombre = ent_nombre.get().strip().upper()
            if not nombre: return messagebox.showerror("Error", "El nombre del modelo es obligatorio.", parent=modal)

            original = modo_edicion.get()
            if original and original != nombre and nombre in CATALOGO_MODELOS:
                return messagebox.showerror("Error", "Ya existe un modelo con ese nombre.", parent=modal)

            img_file = CATALOGO_MODELOS.get(original, {}).get("imagen", "") if original else ""
            pdf_file = CATALOGO_MODELOS.get(original, {}).get("pdf", "") if original else ""

            if ruta_img.get() and os.path.isabs(ruta_img.get()):
                img_file = guardar_archivo_modelo_local(ruta_img.get())
            if ruta_pdf.get() and os.path.isabs(ruta_pdf.get()):
                pdf_file = guardar_archivo_modelo_local(ruta_pdf.get())

            if original and original != nombre:
                del CATALOGO_MODELOS[original]

            CATALOGO_MODELOS[nombre] = {"imagen": img_file, "pdf": pdf_file}
            guardar_modelos_nube(CATALOGO_MODELOS)
            sincronizar_diccionarios_globales()

            messagebox.showinfo("Éxito", "Modelo guardado correctamente.", parent=modal)
            limpiar_formulario()
            actualizar_lista()
            self.actualizar_combobox_modelos()

        ctk.CTkButton(frame_form, text="💾 Guardar Modelo", fg_color="#2980B9", hover_color="#1F618D", text_color="white", command=guardar_modelo_action).grid(row=2, column=0, columnspan=2, pady=10)

        ctk.CTkLabel(modal, text="Modelos Existentes:", font=ctk.CTkFont(size=11, weight="bold"), text_color=("gray40", "gray70")).pack(anchor="w", padx=18, pady=(10, 2))
        scroll_modelos = ctk.CTkScrollableFrame(modal, height=250, fg_color=("gray85", "gray20"), corner_radius=6)
        scroll_modelos.pack(fill="both", expand=True, padx=18, pady=2)

        def limpiar_formulario():
            ent_nombre.delete(0, "end")
            ruta_img.set("")
            ruta_pdf.set("")
            modo_edicion.set("")
            btn_img.configure(text="Seleccionar Foto (Opc)", fg_color="#1F6AA5")
            btn_pdf.configure(text="Seleccionar Plano (Opc)", fg_color="#1F6AA5")

        def editar_modelo(nombre):
            limpiar_formulario()
            modo_edicion.set(nombre)
            ent_nombre.insert(0, nombre)
            mod_data = CATALOGO_MODELOS.get(nombre, {})
            ruta_img.set(mod_data.get("imagen", ""))
            ruta_pdf.set(mod_data.get("pdf", ""))
            if ruta_img.get(): btn_img.configure(text=ruta_img.get(), fg_color="#27AE60")
            if ruta_pdf.get(): btn_pdf.configure(text=ruta_pdf.get(), fg_color="#27AE60")

        def eliminar_modelo(nombre):
            if messagebox.askyesno("Confirmar", f"¿Eliminar el modelo {nombre}?", parent=modal):
                del CATALOGO_MODELOS[nombre]
                guardar_modelos_nube(CATALOGO_MODELOS)
                sincronizar_diccionarios_globales()
                actualizar_lista()
                self.actualizar_combobox_modelos()

        def actualizar_lista():
            for widget in scroll_modelos.winfo_children(): widget.destroy()
            for nom, data in CATALOGO_MODELOS.items():
                row_m = ctk.CTkFrame(scroll_modelos, fg_color="transparent")
                row_m.pack(fill="x", pady=2)
                txt_info = f"📦 {nom}"
                if data.get("imagen"): txt_info += " 🖼️"
                if data.get("pdf"): txt_info += " 📐"
                ctk.CTkLabel(row_m, text=txt_info, font=ctk.CTkFont(size=11), text_color=("black", "white")).pack(side="left", padx=4)
                ctk.CTkButton(row_m, text="✕", width=24, height=22, fg_color="#C0392B", hover_color="#922B21", text_color="white", command=lambda n=nom: eliminar_modelo(n)).pack(side="right", padx=4)
                ctk.CTkButton(row_m, text="✏️", width=35, height=22, fg_color="#F39C12", hover_color="#D68910", text_color="white", command=lambda n=nom: editar_modelo(n)).pack(side="right", padx=4)

        actualizar_lista()

    def actualizar_combobox_modelos(self):
        for fila in self.nuevas_filas:
            opciones = list(CATALOGO_MODELOS.keys()) if CATALOGO_MODELOS else [""]
            fila.combo_modelo.configure(values=opciones)
            if fila.combo_modelo.get() not in CATALOGO_MODELOS:
                fila.combo_modelo.set(opciones[0])
                self.manejador_cambio_modelo(fila.combo_modelo.get(), fila)

    def confirmar_limpieza_base_datos(self):
        if messagebox.askyesno("⚠️ PELIGRO", "¿Estás seguro de ELIMINAR TODO EL HISTORIAL y LOS TRABAJOS ACTIVOS?", parent=self):
            if messagebox.askyesno("Confirmación Final", "¿Desea vaciar la base de datos?", parent=self):
                global DB_TRABAJOS_ANTERIORES, DB_TRABAJOS_TERMINADOS
                DB_TRABAJOS_ANTERIORES = []; DB_TRABAJOS_TERMINADOS = []
                guardar_trabajos_activos(DB_TRABAJOS_ANTERIORES)
                guardar_historial_terminados(DB_TRABAJOS_TERMINADOS)
                self.refrescar_dashboard_completo(); self.actualizar_tabla_terminados_visual()
                self.contador_folio = 1
                if hasattr(self, 'ent_folio'): self.ent_folio.delete(0, "end"); self.ent_folio.insert(0, f"PRD-2026-00{self.contador_folio}")
                messagebox.showinfo("Limpieza Exitosa", "Base de datos reiniciada.", parent=self)

    # --- DISEÑO DE UI ---
    def disenar_encabezado(self):
        frame_header = ctk.CTkFrame(self.scroll_principal, fg_color="transparent")
        frame_header.pack(fill="x", pady=(2, 8), padx=5)

        path_logo = ruta_recurso(os.path.join("assets", "logo.png"))
        if os.path.exists(path_logo):
            try:
                img_logo_pil = Image.open(path_logo).convert("RGBA")
                datas = img_logo_pil.getdata()
                newData = [(255, 255, 255, 0) if item[0]>240 and item[1]>240 and item[2]>240 else item for item in datas]
                img_logo_pil.putdata(newData)
                ctk_logo = ctk.CTkImage(light_image=img_logo_pil, dark_image=img_logo_pil, size=(int(45*(img_logo_pil.size[0]/img_logo_pil.size[1])), 45))
                ctk.CTkLabel(frame_header, image=ctk_logo, text="").pack(side="left", padx=(4, 0))
            except: pass

        ctk.CTkLabel(frame_header, text="CONTROL DE PRODUCCION - SISTEMA SEGURO (ONLINE/OFFLINE)", font=ctk.CTkFont(family="Arial", size=15, weight="bold"), text_color=("black", "white")).pack(side="left", expand=True, fill="x", padx=(10, 10))
        frame_usuario = ctk.CTkFrame(frame_header, fg_color=("gray85", "gray20"), corner_radius=6)
        frame_usuario.pack(side="right", padx=5)
        ctk.CTkLabel(frame_usuario, text=f"👤 {self.info_usuario['nombre']} ({self.rol_actual})", font=ctk.CTkFont(size=11, weight="bold"), text_color=("#2980B9", "#3498DB")).pack(side="left", padx=8, pady=4)

        if self.rol_actual == "Admin":
            ctk.CTkButton(frame_usuario, text="🧹 Limpiar BD", width=75, height=24, font=ctk.CTkFont(size=10, weight="bold"), fg_color="#D35400", hover_color="#A04000", text_color="white", command=self.confirmar_limpieza_base_datos).pack(side="left", padx=2)
            ctk.CTkButton(frame_usuario, text="⚙️ Usrs", width=55, height=24, font=ctk.CTkFont(size=10, weight="bold"), fg_color="#8E44AD", hover_color="#7D3C98", text_color="white", command=self.abrir_modal_gestion_usuarios).pack(side="left", padx=2)
            ctk.CTkButton(frame_usuario, text="🛠 Modelos", width=65, height=24, font=ctk.CTkFont(size=10, weight="bold"), fg_color="#2E86C1", hover_color="#21618C", text_color="white", command=self.abrir_modal_gestion_modelos).pack(side="left", padx=2)

        txt_tema = "☀️ Claro" if cargar_cache_local().get("tema", "Dark") == "Dark" else "🌙 Oscuro"
        self.btn_tema = ctk.CTkButton(frame_usuario, text=txt_tema, width=65, height=24, font=ctk.CTkFont(size=10, weight="bold"), fg_color="#7F8C8D", hover_color="#616A6B", text_color="white", command=self.alternar_tema)
        self.btn_tema.pack(side="left", padx=2)

        ctk.CTkButton(frame_usuario, text="🚪 Salir", width=55, height=24, font=ctk.CTkFont(size=10, weight="bold"), fg_color="#C0392B", hover_color="#922B21", text_color="white", command=self.cerrar_sesion).pack(side="left", padx=2, pady=4)

    def disenar_seccion_solicitud(self):
        card = ctk.CTkFrame(self.scroll_principal, corner_radius=8)
        card.pack(fill="x", pady=5, padx=5)
        ctk.CTkLabel(card, text="1. Solicitud de Producción", font=ctk.CTkFont(size=12, weight="bold"), text_color=("black", "white")).pack(anchor="w", padx=12, pady=6)
        container = ctk.CTkFrame(card, fg_color="transparent")
        container.pack(fill="x", padx=12, pady=(0, 8))
        container.grid_columnconfigure((0, 1, 2, 3), weight=1)

        f_titulos = ctk.CTkFont(size=10, weight="bold")
        for i, text in enumerate(["Folio de Producción", "Fecha de Emisión", "Fecha Límite", "Estatus General"]):
            color_txt = ("gray40", "gray70") if i not in [1,2] else (("#2980B9", "#3498DB") if i==1 else ("#C0392B", "#E74C3C"))
            ctk.CTkLabel(container, text=text, font=f_titulos, text_color=color_txt).grid(row=0, column=i, padx=4, sticky="w")

        self.ent_folio = ctk.CTkEntry(container, justify="center")
        self.ent_folio.grid(row=1, column=0, padx=4, pady=2, sticky="ew")
        self.ent_folio.insert(0, f"PRD-2026-00{self.contador_folio}")
        fecha_servidor = obtener_fecha_internet()
        str_fecha_emi = fecha_servidor.strftime("%d/%m/%Y")
        str_fecha_lim = (fecha_servidor + timedelta(days=7)).strftime("%d/%m/%Y")

        self.ent_fecha = ctk.CTkEntry(container, justify="center", fg_color=("#EAF2F8", "#1F364D"), border_color="#3498DB", text_color=("black", "white"))
        self.ent_fecha.grid(row=1, column=1, padx=4, pady=2, sticky="ew")
        self.ent_fecha.insert(0, str_fecha_emi)
        self.ent_fecha.configure(state="readonly")

        self.ent_fecha_limite = ctk.CTkEntry(container, justify="center", fg_color=("#FDEDEC", "#4A2323"), border_color="#E74C3C", text_color=("black", "white"))
        self.ent_fecha_limite.grid(row=1, column=2, padx=4, pady=2, sticky="ew")
        self.ent_fecha_limite.insert(0, str_fecha_lim)

        self.combo_estatus = ctk.CTkOptionMenu(container, values=["En Proceso", "Completado", "Cancelado"], fg_color=("#F39C12", "#D68910"), button_color=("#D68910", "#CA6F1E"), text_color="white")
        self.combo_estatus.grid(row=1, column=3, padx=4, pady=2, sticky="ew")

    def disenar_seccion_nuevas_ordenes(self):
        self.card_nuevos = ctk.CTkFrame(self.scroll_principal, corner_radius=8)
        self.card_nuevos.pack(fill="x", pady=5, padx=5)

        header_frame = ctk.CTkFrame(self.card_nuevos, fg_color="transparent")
        header_frame.pack(fill="x", padx=12, pady=6)
        ctk.CTkLabel(header_frame, text="2. Nuevas Órdenes a Iniciar", font=ctk.CTkFont(size=12, weight="bold"), text_color=("black", "white")).pack(side="left")

        self.container_filas_nuevas = ctk.CTkFrame(self.card_nuevos, fg_color="transparent")
        self.container_filas_nuevas.pack(fill="x", padx=12, pady=4)
        self.interfaz_agregar_fila_nueva()

        ctk.CTkButton(self.card_nuevos, text="🚀 ENVIAR A PRODUCCIÓN", font=ctk.CTkFont(weight="bold"), fg_color="#2980B9", hover_color="#1F618D", text_color="white", height=34, command=self.operacion_enviar_a_produccion).pack(fill="x", padx=12, pady=8)

    def interfaz_agregar_fila_nueva(self):
        fila = FilaNuevaOrden(self.container_filas_nuevas, self.info_usuario['nombre'], self.manejador_cambio_modelo, self.previsualizar_plano_pdf)
        fila.pack(fill="x", pady=3)
        self.nuevas_filas.append(fila)

    def disenar_seccion_dashboard(self):
        card_dash = ctk.CTkFrame(self.scroll_principal, corner_radius=8)
        card_dash.pack(fill="x", pady=5, padx=5)
        ctk.CTkLabel(card_dash, text="3. Dashboard de Procesos Activos", font=ctk.CTkFont(size=12, weight="bold"), text_color=("black", "white")).pack(anchor="w", padx=12, pady=6)
        self.tabla_frame = ctk.CTkFrame(card_dash, fg_color="transparent")
        self.tabla_frame.pack(fill="x", padx=12, pady=(0, 10))
        headers = ["Tiempo", "Folio", "Total", "Urg.", "Modelo", "F. Límite", "Observaciones", "Preview / Plano", "Solicitante", "Prioridad", "ACCIONES OPERATIVAS", "INDICADOR DE AVANCE"]
        weights = [1, 1, 1, 1, 2, 1, 2, 2, 1, 1, 3, 3]

        for idx, text in enumerate(headers):
            lbl = ctk.CTkLabel(self.tabla_frame, text=text, font=ctk.CTkFont(size=10, weight="bold"), text_color=("gray40", "gray70"), anchor="center")
            lbl.grid(row=0, column=idx, padx=3, pady=5, sticky="ew")
            self.tabla_frame.grid_columnconfigure(idx, weight=weights[idx])

        for datos in DB_TRABAJOS_ANTERIORES: self.inyectar_fila_en_dashboard(datos)

    def disenar_seccion_historial_terminados(self):
        card = ctk.CTkFrame(self.scroll_principal, corner_radius=8)
        card.pack(fill="x", pady=5, padx=5)
        header_hist_frame = ctk.CTkFrame(card, fg_color="transparent")
        header_hist_frame.pack(fill="x", padx=12, pady=6)
        ctk.CTkLabel(header_hist_frame, text="4. Historial de Trabajos Terminados", font=ctk.CTkFont(size=12, weight="bold"), text_color=("black", "white")).pack(side="left")
        ctk.CTkButton(header_hist_frame, text="📊 Descargar Excel", fg_color="#27AE60", hover_color="#1E8449", text_color="white", width=130, height=26, font=ctk.CTkFont(size=11, weight="bold"), command=self.exportar_historial_excel).pack(side="right")

        controls_frame = ctk.CTkFrame(card, fg_color="transparent")
        controls_frame.pack(fill="x", padx=12, pady=(0, 6))
        ctk.CTkLabel(controls_frame, text="🔍 Buscar Folio:", font=ctk.CTkFont(size=11, weight="bold"), text_color=("#2980B9", "#3498DB")).pack(side="left", padx=(0, 6))
        self.ent_buscar_folio = ctk.CTkEntry(controls_frame, width=180, height=28)
        self.ent_buscar_folio.pack(side="left", padx=2)
        self.ent_buscar_folio.bind("<KeyRelease>", self.filtrar_historial_terminados)
        ctk.CTkButton(controls_frame, text="Limpiar", width=65, height=28, fg_color=("gray60", "gray40"), hover_color=("gray50", "gray50"), text_color="white", command=self.limpiar_busqueda_terminados).pack(side="left", padx=6)

        self.pag_frame = ctk.CTkFrame(controls_frame, fg_color="transparent")
        self.pag_frame.pack(side="right")
        ctk.CTkButton(self.pag_frame, text="⬅️", width=35, height=26, fg_color="#2980B9", text_color="white", command=lambda: self.cambiar_pagina_terminados(-1)).pack(side="left", padx=2)
        self.lbl_pag_info = ctk.CTkLabel(self.pag_frame, text="Pág 1/1", font=ctk.CTkFont(size=11, weight="bold"), text_color=("black", "white"))
        self.lbl_pag_info.pack(side="left", padx=6)
        ctk.CTkButton(self.pag_frame, text="➡️", width=35, height=26, fg_color="#2980B9", text_color="white", command=lambda: self.cambiar_pagina_terminados(1)).pack(side="left", padx=2)

        self.tabla_terminados_frame = ctk.CTkFrame(card, fg_color=("gray90", "gray15"), corner_radius=6)
        self.tabla_terminados_frame.pack(fill="x", padx=12, pady=(0, 8))
        headers_term = ["Folio", "Modelo", "Cant.", "Estatus", "F. Inicio", "F. Límite", "F. Entrega", "Solicitante", "Reportó", "Recibió", "Plano", "Detalles"]
        for idx, th in enumerate(headers_term):
            ctk.CTkLabel(self.tabla_terminados_frame, text=th, font=ctk.CTkFont(size=10, weight="bold"), text_color=("gray40", "gray70")).grid(row=0, column=idx, padx=4, pady=5, sticky="ew")
            self.tabla_terminados_frame.grid_columnconfigure(idx, weight=1)
        self.actualizar_tabla_terminados_visual()

    # --- LOGICA OPERATIVA ---
    def operacion_enviar_a_produccion(self):
        folio = self.ent_folio.get().strip()
        f_emi = self.ent_fecha.get().strip()
        f_lim = self.ent_fecha_limite.get().strip()
        if not folio: return messagebox.showerror("Error", "Defina un Folio.")
        for fila in list(self.nuevas_filas):
            datos = fila.obtener_datos()
            datos_completos = {
                "folio": folio, "cantidad": datos["cantidad"], "urgentes": datos["urgentes"], "entregado": 0,
                "modelo": datos["modelo"], "obs": datos["obs"] if datos["obs"] else "Lote Nuevo",
                "prioridad": datos["prioridad"], "solicitante": datos["solicitante"],
                "fecha_inicio": f_emi, "fecha_limite": f_lim, "historial_entregas": []
            }
            DB_TRABAJOS_ANTERIORES.append(datos_completos)
            self.inyectar_fila_en_dashboard(datos_completos)
            fila.destroy()

        guardar_trabajos_activos(DB_TRABAJOS_ANTERIORES)
        self.nuevas_filas.clear()
        self.interfaz_agregar_fila_nueva()
        self.contador_folio += 1
        self.ent_folio.delete(0, "end")
        self.ent_folio.insert(0, f"PRD-2026-00{self.contador_folio}")
        messagebox.showinfo("Línea de Producción", "Enviado a Producción con éxito.")

    def inyectar_fila_en_dashboard(self, datos):
        id_unico = f"item_{id(datos)}_{datos['folio']}"
        row_idx = self.tabla_frame.grid_size()[1] + 1
        widgets_fila = []
        es_inventarios = (self.rol_actual == "Inventarios")
        es_taller = (self.rol_actual == "Taller")

        try:
            d_restantes = (datetime.strptime(datos.get("fecha_limite", ""), "%d/%m/%Y").date() - datetime.now().date()).days
            if d_restantes <= 3: c_sem, txt_sem = "#C0392B", "🔴⚠️"
            elif 4 <= d_restantes <= 7: c_sem, txt_sem = "#D4AC0D", "🟡💡"
            else: c_sem, txt_sem = "#229954", "🟢🛠️"
        except: c_sem, txt_sem = "#229954", "🟢🛠️"

        lbl_sem = ctk.CTkLabel(self.tabla_frame, text=txt_sem, font=ctk.CTkFont(size=10, weight="bold"), fg_color=c_sem, corner_radius=6, height=26, text_color="white")
        lbl_sem.grid(row=row_idx, column=0, pady=4, padx=3, sticky="ew")
        widgets_fila.append(lbl_sem)

        for col, t in enumerate([datos["folio"], f"{datos['cantidad']} pzas", str(datos.get("urgentes", 0)), datos["modelo"], datos.get("fecha_limite", "")]):
            lbl_color = ("#C0392B", "#E74C3C") if col == 2 and t != "0" else ("black", "white")
            lbl = ctk.CTkLabel(self.tabla_frame, text=t, font=ctk.CTkFont(weight="bold"), text_color=lbl_color)
            lbl.grid(row=row_idx, column=col + 1, pady=3, padx=2, sticky="ew")
            widgets_fila.append(lbl)

        txt_obs = datos["obs"] if len(datos["obs"]) <= 18 else datos["obs"][:18] + "..."
        lbl_obs = ctk.CTkLabel(self.tabla_frame, text=txt_obs, text_color=("gray40", "gray70"))
        lbl_obs.grid(row=row_idx, column=6, pady=3, padx=2, sticky="ew")
        if len(datos["obs"]) > 18: ToolTip(lbl_obs, datos["obs"])
        widgets_fila.append(lbl_obs)

        frame_mm = ctk.CTkFrame(self.tabla_frame, fg_color="transparent")
        frame_mm.grid(row=row_idx, column=7, pady=3, padx=2)
        widgets_fila.append(frame_mm)

        btn_img = ctk.CTkButton(frame_mm, text="N/A", width=28, height=28, fg_color=("gray80", "gray20"), text_color=("gray40", "gray70"))
        btn_img.pack(side="left", padx=1)

        archivo_img = CATALOGO_IMAGENES.get(datos["modelo"])
        path_final = obtener_ruta_archivo_modelo(archivo_img)
        if path_final and os.path.exists(path_final):
            try:
                img_pil = Image.open(path_final).convert("RGBA")
                img_ctk_mini = ctk.CTkImage(light_image=img_pil, dark_image=img_pil, size=(28, 28))
                btn_img.configure(image=img_ctk_mini, text="", fg_color="transparent", hover_color="gray25", command=lambda p=path_final, m=datos["modelo"]: self.abrir_ventana_modal_imagen(p, m))
                btn_img.image = img_ctk_mini
            except: pass

        ctk.CTkButton(frame_mm, text="📐 Plano", width=44, height=24, font=ctk.CTkFont(size=9, weight="bold"), fg_color="#8E44AD", hover_color="#7D3C98", text_color="white", command=lambda m=datos["modelo"]: self.previsualizar_plano_pdf(m)).pack(side="left", padx=1)

        lbl_solic = ctk.CTkLabel(self.tabla_frame, text=datos["solicitante"], text_color=("#2980B9", "#3498DB"), font=ctk.CTkFont(weight="bold"))
        lbl_solic.grid(row=row_idx, column=8, pady=3, padx=2, sticky="ew")
        widgets_fila.append(lbl_solic)

        menu_prio = ctk.CTkOptionMenu(self.tabla_frame, values=["1 (Urgente)", "2 (Normal)", "3 (Baja)"], height=24, state="disabled" if es_taller else "normal")
        v_ini = "1 (Urgente)" if str(datos["prioridad"]) == "1" else ("2 (Normal)" if str(datos["prioridad"]) == "2" else "3 (Baja)")
        menu_prio.set(v_ini)
        menu_prio.grid(row=row_idx, column=9, pady=3, padx=2, sticky="ew")
        widgets_fila.append(menu_prio)

        def act_prio(seleccion, d=datos, w=menu_prio):
            d["prioridad"] = seleccion[0]
            if seleccion.startswith("1"):
                w.configure(fg_color=("#E74C3C", "#C0392B"), button_color=("#C0392B", "#922B21"), text_color="white")
            elif seleccion.startswith("2"):
                w.configure(fg_color=("#F39C12", "#D68910"), button_color=("#D68910", "#CA6F1E"), text_color="white")
            else:
                w.configure(fg_color=("gray60", "gray50"), button_color=("gray50", "gray40"), text_color="white")
            guardar_trabajos_activos(DB_TRABAJOS_ANTERIORES)

        menu_prio.configure(command=act_prio)
        act_prio(v_ini)

        f_acc = ctk.CTkFrame(self.tabla_frame, fg_color="transparent")
        f_acc.grid(row=row_idx, column=10, pady=3, padx=2)
        widgets_fila.append(f_acc)

        btn_parcial = ctk.CTkButton(f_acc, text="📦 Disp.", width=48, height=24, font=ctk.CTkFont(size=9, weight="bold"), fg_color="#2980B9", text_color="white", state="disabled" if es_inventarios else "normal", command=lambda: self.abrir_ventana_modal_material_disponible(id_unico))
        btn_parcial.pack(side="left", padx=1)
        btn_term = ctk.CTkButton(f_acc, text="🏁 Term", width=52, height=24, font=ctk.CTkFont(size=9, weight="bold"), fg_color=("gray70", "gray30"), text_color="white", state="disabled", command=lambda: self.abrir_ventana_cierre_final(id_unico))
        btn_term.pack(side="left", padx=1)
        btn_detalles = ctk.CTkButton(f_acc, text="📜", width=26, height=24, font=ctk.CTkFont(size=11), fg_color="#34495E", hover_color="#2C3E50", text_color="white", command=lambda d=datos: self.abrir_modal_detalles_terminado(d))
        btn_detalles.pack(side="left", padx=1)
        btn_can = ctk.CTkButton(f_acc, text="✕", width=24, height=24, font=ctk.CTkFont(size=10, weight="bold"), fg_color="#C0392B", text_color="white", state="disabled" if es_taller else "normal", command=lambda: self.abrir_modal_cancelar_orden(id_unico))
        if datos["entregado"] == 0: btn_can.pack(side="left", padx=1)

        f_av = ctk.CTkFrame(self.tabla_frame, fg_color="transparent")
        f_av.grid(row=row_idx, column=11, pady=3, padx=4, sticky="ew")
        f_av.grid_columnconfigure(0, weight=1)
        widgets_fila.append(f_av)

        p_bar = ctk.CTkProgressBar(f_av, height=6)
        p_bar.grid(row=0, column=0, sticky="ew", pady=(0, 2))
        btn_txt = ctk.CTkButton(f_av, text="", font=ctk.CTkFont(size=10, weight="bold"), fg_color="transparent", height=12)
        if not es_inventarios: btn_txt.configure(hover_color=("gray85", "gray25"), command=lambda: self.abrir_ventana_modal_material_disponible(id_unico))
        else: btn_txt.configure(hover=False)
        btn_txt.grid(row=1, column=0, sticky="ew")

        self.referencias_dashboard[id_unico] = {"datos": datos, "progress_bar": p_bar, "btn_text": btn_txt, "btn_terminar": btn_term, "btn_cancelar": btn_can, "widgets_fila": widgets_fila}
        self.recalcular_progreso_fila(id_unico)

    def recalcular_progreso_fila(self, id_unico):
        if id_unico not in self.referencias_dashboard: return
        ref = self.referencias_dashboard[id_unico]
        tot, ent = ref["datos"]["cantidad"], ref["datos"]["entregado"]
        prog = (min(ent, tot) / tot) if tot > 0 else 0.0
        ref["progress_bar"].set(prog)
        if ent > 0: ref["btn_cancelar"].pack_forget()
        else: ref["btn_cancelar"].pack(side="left", padx=1)

        if ent >= tot:
            ref["btn_text"].configure(text=f"Completo [{ent}/{tot}]", text_color=("#27AE60", "#2ECC71"))
            ref["btn_terminar"].configure(state="normal", fg_color="#27AE60")
        else:
            ref["btn_text"].configure(text=f"Avance {int(prog*100)}% [{ent}/{tot}]", text_color=("#2980B9", "#3498DB"))
            ref["btn_terminar"].configure(state="disabled", fg_color=("gray70", "gray30"))

    def abrir_ventana_modal_material_disponible(self, id_unico):
        ref = self.referencias_dashboard[id_unico]; datos = ref["datos"]
        modal = ctk.CTkToplevel(self)
        self.centrar_ventana_modal(modal, 450, 520)
        modal.attributes("-topmost", True); modal.grab_set()

        ctk.CTkLabel(modal, text=f"📦 Registrar Material Terminado: [{datos['modelo']}]", font=ctk.CTkFont(size=14, weight="bold"), text_color=("#2980B9", "#3498DB")).pack(pady=(15, 10))
        ctk.CTkLabel(modal, text="📅 Fecha de aviso (Editable):", font=ctk.CTkFont(size=11, weight="bold"), text_color=("black", "white")).pack(anchor="w", padx=25)
        ent_fecha = ctk.CTkEntry(modal, justify="center", height=32)
        ent_fecha.insert(0, datetime.now().strftime("%d/%m/%Y")); ent_fecha.pack(fill="x", padx=25, pady=(2, 8))

        ctk.CTkLabel(modal, text=f"🔢 Cantidad terminada (Pendientes: {max(0, datos['cantidad'] - datos.get('entregado', 0))} pzas):", font=ctk.CTkFont(size=11, weight="bold"), text_color=("black", "white")).pack(anchor="w", padx=25)
        ent_cant = ctk.CTkEntry(modal, justify="center", height=32); ent_cant.pack(fill="x", padx=25, pady=(2, 8))

        ctk.CTkLabel(modal, text="👤 Quién reporta:", font=ctk.CTkFont(size=11, weight="bold"), text_color=("black", "white")).pack(anchor="w", padx=25)
        ent_pers = ctk.CTkEntry(modal, justify="center", height=32)
        ent_pers.insert(0, self.info_usuario['nombre']); ent_pers.pack(fill="x", padx=25, pady=(2, 8))

        ctk.CTkLabel(modal, text="📝 Observaciones (Opcional):", font=ctk.CTkFont(size=11, weight="bold"), text_color=("black", "white")).pack(anchor="w", padx=25)
        ent_obs = ctk.CTkEntry(modal, justify="center", height=32); ent_obs.pack(fill="x", padx=25, pady=(2, 15))

        def guardar_aviso_material():
            if not ent_cant.get().isdigit() or int(ent_cant.get()) <= 0: return messagebox.showerror("Error", "Cantidad inválida.", parent=modal)
            cant_reportada = int(ent_cant.get()); exc = 0
            nuevo_total = datos.get("entregado", 0) + cant_reportada
            if nuevo_total > datos.get("cantidad", 0): exc = nuevo_total - max(datos.get("cantidad", 0), datos.get("entregado", 0))

            if "historial_entregas" not in datos: datos["historial_entregas"] = []
            datos["historial_entregas"].append({"fecha": ent_fecha.get().strip(), "cantidad": cant_reportada, "persona": ent_pers.get().strip() or self.info_usuario['nombre'], "excedente": exc, "observaciones": ent_obs.get().strip()})
            datos["entregado"] = nuevo_total
            guardar_trabajos_activos(DB_TRABAJOS_ANTERIORES); self.recalcular_progreso_fila(id_unico)
            modal.destroy()

        ctk.CTkButton(modal, text="💾 Registrar Material Disponible", fg_color="#27AE60", hover_color="#1E8449", height=36, font=ctk.CTkFont(weight="bold"), text_color="white", command=guardar_aviso_material).pack(fill="x", padx=25, pady=10)

    def abrir_ventana_cierre_final(self, id_unico):
        ref = self.referencias_dashboard[id_unico]; datos = ref["datos"]
        modal_c = ctk.CTkToplevel(self)
        self.centrar_ventana_modal(modal_c, 450, 480)
        modal_c.attributes("-topmost", True); modal_c.grab_set()

        ctk.CTkLabel(modal_c, text=f"🏁 Cierre Definitivo de Orden: [{datos['modelo']}]", font=ctk.CTkFont(size=14, weight="bold"), text_color=("#27AE60", "#2ECC71")).pack(pady=(15, 10))
        ctk.CTkLabel(modal_c, text="📅 Fecha de Cierre:", font=ctk.CTkFont(size=11, weight="bold"), text_color=("black", "white")).pack(anchor="w", padx=25)
        ent_fecha_fin = ctk.CTkEntry(modal_c, justify="center", height=32); ent_fecha_fin.insert(0, datetime.now().strftime("%d/%m/%Y")); ent_fecha_fin.pack(fill="x", padx=25, pady=(2, 8))
        ctk.CTkLabel(modal_c, text="👤 ¿Quién entregó?", font=ctk.CTkFont(size=11, weight="bold"), text_color=("black", "white")).pack(anchor="w", padx=25)
        ent_entrego = ctk.CTkEntry(modal_c, justify="center", height=32); ent_entrego.insert(0, self.info_usuario['nombre']); ent_entrego.pack(fill="x", padx=25, pady=(2, 8))
        ctk.CTkLabel(modal_c, text="👤 ¿Quién Recibe?", font=ctk.CTkFont(size=11, weight="bold"), text_color=("black", "white")).pack(anchor="w", padx=25)
        ent_recibe = ctk.CTkEntry(modal_c, justify="center", height=32); ent_recibe.pack(fill="x", padx=25, pady=(2, 8))
        ctk.CTkLabel(modal_c, text="📝 Observaciones Finales:", font=ctk.CTkFont(size=11, weight="bold"), text_color=("black", "white")).pack(anchor="w", padx=25)
        ent_obs_fin = ctk.CTkEntry(modal_c, justify="center", height=32); ent_obs_fin.pack(fill="x", padx=25, pady=(2, 15))

        def conf_cierre():
            if not ent_recibe.get().strip(): return messagebox.showerror("Error", "Indique quién recibe.", parent=modal_c)
            historial_final = datos.get("historial_entregas", [])
            if ent_obs_fin.get().strip(): historial_final.append({"fecha": ent_fecha_fin.get() or datetime.now().strftime("%d/%m/%Y"), "cantidad": 0, "persona": ent_entrego.get() or self.info_usuario['nombre'], "excedente": 0, "observaciones": f"Nota de Cierre: {ent_obs_fin.get()}"})

            reg_t = {
                "folio": datos["folio"], "modelo": datos["modelo"], "cantidad": datos["cantidad"], "estatus": "✅ Completo",
                "fecha_inicio": datos["fecha_inicio"], "fecha_entrega": ent_fecha_fin.get() or datetime.now().strftime("%d/%m/%Y"),
                "solicitante": datos.get("solicitante", "N/A"), "entrego": ent_entrego.get() or self.info_usuario['nombre'],
                "recibio": ent_recibe.get().strip(), "historial_parcialidades": historial_final
            }
            DB_TRABAJOS_TERMINADOS.append(reg_t)
            if datos in DB_TRABAJOS_ANTERIORES: DB_TRABAJOS_ANTERIORES.remove(datos)
            guardar_historial_terminados(DB_TRABAJOS_TERMINADOS); guardar_trabajos_activos(DB_TRABAJOS_ANTERIORES)
            self.actualizar_tabla_terminados_visual()
            for w in ref["widgets_fila"]: w.destroy()
            del self.referencias_dashboard[id_unico]; modal_c.destroy()

        ctk.CTkButton(modal_c, text="📦 Archivar y Completar", fg_color="#27AE60", hover_color="#1E8449", height=36, font=ctk.CTkFont(weight="bold"), text_color="white", command=conf_cierre).pack(fill="x", padx=25, pady=10)

    def abrir_modal_cancelar_orden(self, id_unico):
        ref = self.referencias_dashboard[id_unico]; datos = ref["datos"]
        modal_can = ctk.CTkToplevel(self)
        self.centrar_ventana_modal(modal_can, 450, 320)
        modal_can.attributes("-topmost", True); modal_can.grab_set()

        ctk.CTkLabel(modal_can, text=f"Cancelar Orden: [{datos['folio']}]", font=ctk.CTkFont(size=12, weight="bold"), text_color=("#C0392B", "#E74C3C")).pack(pady=12)
        txt_motivo = ctk.CTkTextbox(modal_can, height=120, fg_color=("gray90", "gray15"), text_color=("black", "white")); txt_motivo.pack(fill="x", padx=25, pady=6)

        def ejecutar_descarte():
            motivo = txt_motivo.get("1.0", "end-1c").strip()
            if not motivo: return messagebox.showerror("Error", "Debe redactar el motivo.", parent=modal_can)
            reg = {
                "folio": datos["folio"], "modelo": datos["modelo"], "cantidad": datos["cantidad"], "estatus": f"❌ Cancelado ({motivo})",
                "fecha_inicio": datos["fecha_inicio"], "fecha_entrega": datetime.now().strftime("%d/%m/%Y"),
                "solicitante": datos.get("solicitante", "N/A"), "entrego": self.info_usuario['nombre'], "recibio": "N/A",
                "historial_parcialidades": datos.get("historial_entregas", []), "motivo_cancelacion": motivo
            }
            DB_TRABAJOS_TERMINADOS.append(reg)
            if datos in DB_TRABAJOS_ANTERIORES: DB_TRABAJOS_ANTERIORES.remove(datos)
            guardar_historial_terminados(DB_TRABAJOS_TERMINADOS); guardar_trabajos_activos(DB_TRABAJOS_ANTERIORES)
            self.actualizar_tabla_terminados_visual()
            for w in ref["widgets_fila"]: w.destroy()
            del self.referencias_dashboard[id_unico]; modal_can.destroy()

        ctk.CTkButton(modal_can, text="💥 Confirmar Cancelación", fg_color="#C0392B", hover_color="#922B21", height=34, text_color="white", command=ejecutar_descarte).pack(fill="x", padx=25, pady=10)

    def abrir_modal_detalles_terminado(self, datos):
        modal = ctk.CTkToplevel(self)
        self.centrar_ventana_modal(modal, 550, 480)
        modal.attributes("-topmost", True); modal.grab_set()

        ctk.CTkLabel(modal, text=f"Historial de Material: [{datos['modelo']}]", font=ctk.CTkFont(size=14, weight="bold"), text_color=("#2980B9", "#3498DB")).pack(pady=10)
        ctk.CTkLabel(modal, text=f"👤 Solicitante: {datos.get('solicitante', 'N/A')}", font=ctk.CTkFont(size=12, weight="bold"), text_color=("#D4AC0D", "#F1C40F")).pack(pady=(0, 5))
        scroll = ctk.CTkScrollableFrame(modal, fg_color=("gray90", "gray15")); scroll.pack(fill="both", expand=True, padx=15, pady=5)

        if "motivo_cancelacion" in datos: ctk.CTkLabel(scroll, text=f"CANCELADO:\n{datos['motivo_cancelacion']}", text_color=("#C0392B", "#E74C3C"), font=ctk.CTkFont(weight="bold")).pack(pady=10)

        parcs = datos.get("historial_parcialidades", datos.get("historial_entregas", []))
        if not parcs: ctk.CTkLabel(scroll, text="Sin avisos de material.", text_color=("gray40", "gray70")).pack(pady=10)
        else:
            for i, p in enumerate(parcs, start=1):
                f_e = ctk.CTkFrame(scroll, fg_color=("gray85", "gray20"), corner_radius=6); f_e.pack(fill="x", pady=5, padx=5, ipadx=5, ipady=5)
                ctk.CTkLabel(f_e, text=f"📦 Aviso #{i} | 📅 {p.get('fecha')} | 👤 {p.get('persona')}", font=ctk.CTkFont(size=12, weight="bold"), text_color=("#D4AC0D", "#F1C40F"), anchor="w").pack(fill="x", padx=8)
                ctk.CTkLabel(f_e, text=f"✔️ Disponible: {p.get('cantidad')} pzas", font=ctk.CTkFont(size=11), text_color=("black", "white"), anchor="w").pack(fill="x", padx=8)
                if p.get('excedente', 0) > 0: ctk.CTkLabel(f_e, text=f"⚠ Excedente: +{p.get('excedente')} pzas", font=ctk.CTkFont(size=11, weight="bold"), text_color=("#C0392B", "#E74C3C"), anchor="w").pack(fill="x", padx=8)
                if p.get('observaciones', '').strip(): ctk.CTkLabel(f_e, text=f"📝 Obs: {p.get('observaciones')}", font=ctk.CTkFont(size=11, slant="italic"), text_color=("gray40", "gray70"), anchor="w").pack(fill="x", padx=8)
        ctk.CTkButton(modal, text="Cerrar", width=120, fg_color=("gray60", "gray40"), hover_color=("gray50", "gray50"), text_color="white", command=modal.destroy).pack(pady=12)

    def abrir_ventana_modal_imagen(self, path_img, modelo_name):
        modal = ctk.CTkToplevel(self)
        self.centrar_ventana_modal(modal, 500, 560)
        modal.attributes("-topmost", True); modal.grab_set()
        try:
            pil_img = Image.open(path_img).convert("RGBA")
            img_hd = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(400, 400))
            ctk.CTkLabel(modal, text=f"Vista Previa: {modelo_name}", font=ctk.CTkFont(size=12, weight="bold"), text_color=("#2980B9", "#3498DB")).pack(pady=10)
            ctk.CTkLabel(modal, image=img_hd, text="", fg_color="transparent").pack(pady=4, padx=15, expand=True)
            ctk.CTkButton(modal, text="Cerrar", fg_color=("gray60", "gray40"), text_color="white", command=modal.destroy).pack(pady=10)
        except Exception as e: ctk.CTkLabel(modal, text=f"Error:\n{e}", text_color="red").pack(pady=30)

    def previsualizar_plano_pdf(self, modelo_name):
        nombre_pdf = CATALOGO_PLANOS_PDF.get(modelo_name, "")
        path_pdf = obtener_ruta_archivo_modelo(nombre_pdf)
        if not path_pdf or not os.path.exists(path_pdf): return self.abrir_modal_plano_virtual(modelo_name)
        if not EXISTE_FITZ: return messagebox.showwarning("Librería Faltante", "Instala PyMuPDF para ver PDFs:\npip install PyMuPDF")

        modal_visor = ctk.CTkToplevel(self)
        self.centrar_ventana_modal(modal_visor, 850, 850)
        modal_visor.attributes("-topmost", True); modal_visor.grab_set()
        try:
            doc = fitz.open(path_pdf)
            pagina_actual = [0]; escala_zoom = [2.0]
            frame_controles = ctk.CTkFrame(modal_visor, fg_color="transparent"); frame_controles.pack(fill="x", padx=15, pady=10)
            lbl_info = ctk.CTkLabel(frame_controles, text="", font=ctk.CTkFont(size=12, weight="bold"), text_color=("#2980B9", "#3498DB")); lbl_info.pack(side="left")

            frame_c = ctk.CTkFrame(modal_visor, fg_color="gray15"); frame_c.pack(fill="both", expand=True, padx=15, pady=5)
            canvas_pdf = tk.Canvas(frame_c, bg="#2B2B2B", highlightthickness=0)
            scroll_y = ctk.CTkScrollbar(frame_c, orientation="vertical", command=canvas_pdf.yview); scroll_y.pack(side="right", fill="y")
            scroll_x = ctk.CTkScrollbar(frame_c, orientation="horizontal", command=canvas_pdf.xview); scroll_x.pack(side="bottom", fill="x")
            canvas_pdf.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set); canvas_pdf.pack(side="left", fill="both", expand=True)
            img_on_c = canvas_pdf.create_image(0, 0, anchor="nw")

            def renderizar_pagina():
                mat = fitz.Matrix(escala_zoom[0], escala_zoom[0])
                pix = doc[pagina_actual[0]].get_pixmap(matrix=mat)
                img_path = f"temp_{id(modal_visor)}.png"; pix.save(img_path)
                pil_img = Image.open(img_path)
                foto_tk = ImageTk.PhotoImage(pil_img)
                canvas_pdf.itemconfig(img_on_c, image=foto_tk); canvas_pdf.image = foto_tk
                canvas_pdf.configure(scrollregion=(0, 0, pil_img.size[0], pil_img.size[1]))
                lbl_info.configure(text=f"Pág {pagina_actual[0]+1}/{len(doc)} | Zoom: {int(escala_zoom[0]*100)}%")
                if os.path.exists(img_path): os.remove(img_path)

            ctk.CTkButton(frame_controles, text="▶ Sig", width=60, text_color="white", command=lambda: [pagina_actual.__setitem__(0, min(len(doc)-1, pagina_actual[0]+1)), renderizar_pagina()]).pack(side="right", padx=2)
            ctk.CTkButton(frame_controles, text="◀ Ant", width=60, text_color="white", command=lambda: [pagina_actual.__setitem__(0, max(0, pagina_actual[0]-1)), renderizar_pagina()]).pack(side="right", padx=(15, 2))
            ctk.CTkButton(frame_controles, text="➕", width=35, text_color="white", command=lambda: [escala_zoom.__setitem__(0, min(5.0, escala_zoom[0]+0.5)), renderizar_pagina()]).pack(side="right", padx=2)
            ctk.CTkButton(frame_controles, text="➖", width=35, text_color="white", command=lambda: [escala_zoom.__setitem__(0, max(1.0, escala_zoom[0]-0.5)), renderizar_pagina()]).pack(side="right", padx=2)
            renderizar_pagina()
        except Exception as e: modal_visor.destroy()

    def abrir_modal_plano_virtual(self, modelo_name):
        modal = ctk.CTkToplevel(self)
        self.centrar_ventana_modal(modal, 520, 300)
        modal.attributes("-topmost", True); modal.grab_set()
        ctk.CTkLabel(modal, text=f"Sin Plano Asignado: [{modelo_name}]", font=ctk.CTkFont(size=13, weight="bold"), text_color=("#8E44AD", "#8E44AD")).pack(pady=40)
        ctk.CTkButton(modal, text="Cerrar", fg_color=("gray60", "gray40"), text_color="white", command=modal.destroy).pack(pady=10)

    def manejador_cambio_modelo(self, modelo_seleccionado, widget_fila=None):
        if not widget_fila: return
        archivo_img = CATALOGO_IMAGENES.get(modelo_seleccionado)
        path_final = obtener_ruta_archivo_modelo(archivo_img)
        if path_final and os.path.exists(path_final):
            try:
                img_pil = Image.open(path_final).convert("RGBA")
                img_ctk = ctk.CTkImage(light_image=img_pil, dark_image=img_pil, size=(32, 32))
                widget_fila.lbl_preview.configure(image=img_ctk, text="")
                widget_fila.lbl_preview.image = img_ctk
            except: widget_fila.lbl_preview.configure(image=None, text="Error")
        else: widget_fila.lbl_preview.configure(image=None, text="N/A")

    def filtrar_historial_terminados(self, event=None):
        self.filtro_folio_busqueda = self.ent_buscar_folio.get().strip().upper()
        self.pagina_actual_term = 0; self.actualizar_tabla_terminados_visual()

    def limpiar_busqueda_terminados(self):
        self.ent_buscar_folio.delete(0, "end")
        self.filtro_folio_busqueda = ""; self.pagina_actual_term = 0
        self.actualizar_tabla_terminados_visual()

    def cambiar_pagina_terminados(self, direccion):
        t_filtrados = [r for r in DB_TRABAJOS_TERMINADOS if not self.filtro_folio_busqueda or self.filtro_folio_busqueda in r["folio"].upper()]
        tot_pag = max(1, (len(t_filtrados) + self.elementos_por_pagina - 1) // self.elementos_por_pagina)
        if 0 <= self.pagina_actual_term + direccion < tot_pag:
            self.pagina_actual_term += direccion; self.actualizar_tabla_terminados_visual()

    def actualizar_tabla_terminados_visual(self):
        for w in self.tabla_terminados_frame.winfo_children():
            if int(w.grid_info().get("row", 0)) > 0: w.destroy()
        t_filtrados = [r for r in DB_TRABAJOS_TERMINADOS if not self.filtro_folio_busqueda or self.filtro_folio_busqueda in r["folio"].upper()]
        tot_elem = len(t_filtrados)
        tot_pag = max(1, (tot_elem + self.elementos_por_pagina - 1) // self.elementos_por_pagina)
        if self.pagina_actual_term >= tot_pag and tot_pag > 0: self.pagina_actual_term = tot_pag - 1

        ini = self.pagina_actual_term * self.elementos_por_pagina
        fin = min(ini + self.elementos_por_pagina, tot_elem)
        self.lbl_pag_info.configure(text=f"Pág {self.pagina_actual_term + 1}/{tot_pag} ({tot_elem} reg.)")

        for idx, reg in enumerate(t_filtrados[ini:fin], start=1):
            ctk.CTkLabel(self.tabla_terminados_frame, text=reg["folio"], font=ctk.CTkFont(size=11), text_color=("black", "white")).grid(row=idx, column=0, padx=4, pady=3, sticky="ew")
            ctk.CTkLabel(self.tabla_terminados_frame, text=reg["modelo"], font=ctk.CTkFont(size=11, weight="bold"), text_color=("black", "white")).grid(row=idx, column=1, padx=4, pady=3, sticky="ew")
            ctk.CTkLabel(self.tabla_terminados_frame, text=str(reg["cantidad"]), font=ctk.CTkFont(size=11), text_color=("black", "white")).grid(row=idx, column=2, padx=4, pady=3, sticky="ew")
            
            c_est = ("#C0392B", "#E74C3C") if "Cancelado" in reg["estatus"] else (("#27AE60", "#2ECC71") if "Completo" in reg["estatus"] else ("#D68910", "#F39C12"))
            ctk.CTkLabel(self.tabla_terminados_frame, text=reg["estatus"], font=ctk.CTkFont(size=10, weight="bold"), text_color=c_est).grid(row=idx, column=3, padx=4, pady=3, sticky="ew")
            
            ctk.CTkLabel(self.tabla_terminados_frame, text=reg.get("fecha_inicio", "N/A"), font=ctk.CTkFont(size=11), text_color=("black", "white")).grid(row=idx, column=4, padx=4, pady=3, sticky="ew")
            ctk.CTkLabel(self.tabla_terminados_frame, text=reg.get("fecha_limite", "N/A"), font=ctk.CTkFont(size=11), text_color=("black", "white")).grid(row=idx, column=5, padx=4, pady=3, sticky="ew")
            ctk.CTkLabel(self.tabla_terminados_frame, text=reg.get("fecha_entrega", "N/A"), font=ctk.CTkFont(size=11), text_color=("#2980B9", "#3498DB")).grid(row=idx, column=6, padx=4, pady=3, sticky="ew")
            ctk.CTkLabel(self.tabla_terminados_frame, text=reg.get("solicitante", "N/A"), font=ctk.CTkFont(size=11, weight="bold"), text_color=("#D4AC0D", "#F1C40F")).grid(row=idx, column=7, padx=4, pady=3, sticky="ew")
            ctk.CTkLabel(self.tabla_terminados_frame, text=reg.get("entrego", "N/A"), font=ctk.CTkFont(size=11), text_color=("black", "white")).grid(row=idx, column=8, padx=4, pady=3, sticky="ew")
            ctk.CTkLabel(self.tabla_terminados_frame, text=reg.get("recibio", "N/A"), font=ctk.CTkFont(size=11), text_color=("black", "white")).grid(row=idx, column=9, padx=4, pady=3, sticky="ew")
            ctk.CTkButton(self.tabla_terminados_frame, text="📐", width=26, height=22, fg_color="#8E44AD", hover_color="#7D3C98", text_color="white", command=lambda m=reg["modelo"]: self.previsualizar_plano_pdf(m)).grid(row=idx, column=10, padx=4, pady=3)
            ctk.CTkButton(self.tabla_terminados_frame, text="📜", width=26, height=22, fg_color="#34495E", hover_color="#2C3E50", text_color="white", command=lambda d=reg: self.abrir_modal_detalles_terminado(d)).grid(row=idx, column=11, padx=4, pady=3)

if __name__ == "__main__":
    sesion = leer_sesion()
    if sesion and "username" in sesion:
        app = AppControlProduccion(sesion["username"])
        app.mainloop()
    else:
        login = VentanaLogin(lambda u: AppControlProduccion(u).mainloop())
        login.mainloop()