import os
import sys
import json
import subprocess
import requests
import threading
import customtkinter as ctk
from tkinter import messagebox

# Librerías de Firebase
import firebase_admin
from firebase_admin import credentials, db

# ==========================================
# CONFIGURACIÓN ESTÉTICA GLOBAL
# ==========================================
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

URL_FIREBASE = 'https://produccion-led-mexico-default-rtdb.firebaseio.com'
NODO_VERSION = 'version_app/version'
REPO_GITHUB = "solarfactorymx/INVENTARIO"
NOMBRE_EXE = "main5.exe"
ARCHIVO_VERSION_LOCAL = "version_local.txt"

def ruta_recurso(nombre_archivo):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, nombre_archivo)

class LanzadorActualizacion(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("LED MEXICO - Actualizador")
        self.geometry("440x240")
        self.resizable(False, False)
        self.eval('tk::PlaceWindow . center')

        # Contenedor principal con diseño moderno
        self.frame_principal = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_principal.pack(fill="both", expand=True, padx=20, pady=20)

        # Título corporativo
        self.lbl_titulo = ctk.CTkLabel(
            self.frame_principal, 
            text="🚀 Control de Producción", 
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color="#3498DB"
        )
        self.lbl_titulo.pack(pady=(5, 5))

        # Etiqueta de estado dinámica
        self.lbl_estado = ctk.CTkLabel(
            self.frame_principal, 
            text="Conectando con el servidor...", 
            font=ctk.CTkFont(size=12),
            text_color="gray70"
        )
        self.lbl_estado.pack(pady=(10, 15))

        # Barra de progreso moderna de CustomTkinter
        self.progress_bar = ctk.CTkProgressBar(self.frame_principal, width=380, height=14)
        self.progress_bar.pack(pady=10)
        self.progress_bar.set(0)

        # Porcentaje de descarga visual
        self.lbl_porcentaje = ctk.CTkLabel(
            self.frame_principal, 
            text="0%", 
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#2ECC71"
        )
        self.lbl_porcentaje.pack(pady=(5, 0))

        # Iniciar verificación en segundo plano
        threading.Thread(target=self.proceso_actualizacion, daemon=True).start()

    def inicializar_firebase(self):
        if not firebase_admin._apps:
            ruta_cred = ruta_recurso("credenciales.json")
            if os.path.exists(ruta_cred):
                with open(ruta_cred, "r", encoding="utf-8") as f:
                    cred_dict = json.load(f)
                cred = credentials.Certificate(cred_dict)
                firebase_admin.initialize_app(cred, {'databaseURL': URL_FIREBASE})
                return True
            return False
        return True

    def obtener_version_local(self):
        if os.path.exists(ARCHIVO_VERSION_LOCAL):
            with open(ARCHIVO_VERSION_LOCAL, "r", encoding="utf-8") as f:
                return f.read().strip()
        return "0.0"

    def guardar_version_local(self, version):
        with open(ARCHIVO_VERSION_LOCAL, "w", encoding="utf-8") as f:
            f.write(version)

    def ejecutar_app_principal(self):
        if os.path.exists(NOMBRE_EXE):
            subprocess.Popen([NOMBRE_EXE])
        else:
            messagebox.showerror("Error", f"No se encontró {NOMBRE_EXE}. Verifique los archivos.")
        self.destroy()
        sys.exit()

    def proceso_actualizacion(self):
        if not self.inicializar_firebase():
            self.lbl_estado.configure(text="⚠️️ Credenciales no encontradas. Iniciando local...")
            self.after(2000, self.ejecutar_app_principal)
            return

        try:
            version_nube = str(db.reference(NODO_VERSION).get())
            version_local = self.obtener_version_local()
        except Exception:
            self.lbl_estado.configure(text="⚠️ Sin conexión a la red. Iniciando modo offline...")
            self.after(2000, self.ejecutar_app_principal)
            return

        if version_nube != version_local and version_nube != "None":
            self.lbl_estado.configure(text=f"Nueva versión disponible ({version_nube}). Descargando...")
            self.descargar_actualizacion(version_nube)
        else:
            self.lbl_estado.configure(text="✅ Sistema al día. Abriendo aplicación...")
            self.progress_bar.set(1.0)
            self.lbl_porcentaje.configure(text="100%")
            self.after(1000, self.ejecutar_app_principal)

    def descargar_actualizacion(self, version_nube):
        url_descarga = f"https://github.com/{REPO_GITHUB}/releases/download/{version_nube}/{NOMBRE_EXE}"
        
        try:
            respuesta = requests.get(url_descarga, stream=True)
            respuesta.raise_for_status()
            
            tamano_total = int(respuesta.headers.get('content-length', 0))
            tamano_descargado = 0
            
            with open(NOMBRE_EXE, 'wb') as f:
                for chunk in respuesta.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        tamano_descargado += len(chunk)
                        if tamano_total > 0:
                            progreso = tamano_descargado / tamano_total
                            porcentaje = int(progreso * 100)
                            # Actualizar la barra y el texto desde el hilo principal
                            self.after(0, lambda p=progreso, por=porcentaje: [
                                self.progress_bar.set(p),
                                self.lbl_porcentaje.configure(text=f"{por}%")
                            ])

            self.guardar_version_local(version_nube)
            self.after(0, lambda: self.lbl_estado.configure(text="🎉 ¡Actualización exitosa!"))
            self.after(1500, self.ejecutar_app_principal)

        except Exception as e:
            messagebox.showerror("Error de Descarga", f"No se pudo descargar la actualización:\n{e}")
            self.ejecutar_app_principal()

if __name__ == "__main__":
    app = LanzadorActualizacion()
    app.mainloop()