<p align="center">
  <img src="logo.png" alt="FrameForge Logo" width="128">
</p>

# FrameForge 🎬

Estrai fotogrammi dai tuoi video e salvali come immagini PNG, con report hash PDF per la verifica di integrità.

![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)
![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey?logo=windows)

## ✨ Funzionalità

- **Estrazione fotogrammi** da qualsiasi formato video (MP4, AVI, MOV, MKV, ecc.)
- **Drag & Drop** per aggiungere video rapidamente
- **FPS personalizzabile** — usa gli FPS originali del video o impostane di custom
- **Report PDF** con hash SHA-256 e MD5 per ogni fotogramma esportato
- **Dati del caso** — inserisci numero caso, codice reperto e operatore per report forensi
- **Interfaccia moderna** con tema dark (Tokyo Night palette)
- **Eseguibile standalone** — nessuna installazione Python necessaria

## 🚀 Installazione

### Eseguibile (consigliato)
Scarica l'ultima release dalla sezione [Releases](../../releases) ed esegui `FrameForge.exe`.

### Da sorgente
```bash
# Clona la repository
git clone https://github.com/jpaladins/FrameForge.git
cd FrameForge

# Installa le dipendenze
pip install -r requirements.txt

# Avvia l'applicazione
python frameforge.py
```

## 📦 Dipendenze

- `opencv-python` — elaborazione video
- `customtkinter` — interfaccia grafica moderna
- `Pillow` — gestione immagini
- `reportlab` — generazione report PDF
- `windnd` — supporto drag & drop su Windows

## 🔨 Build dell'eseguibile

```bash
pip install pyinstaller
python -m PyInstaller FrameForge.spec --noconfirm
```

L'eseguibile verrà generato in `dist/FrameForge.exe`.

## 📄 Licenza

Questo progetto è distribuito sotto licenza MIT. Vedi il file [LICENSE](LICENSE) per i dettagli.

## 👤 Autore

**Michele Paladini**

---

*Developed with ❤️ by Michele Paladini*
