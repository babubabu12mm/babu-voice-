# Antigravity Android Voice Assistant

A complete, production-ready Android Voice Assistant application built with Python, Kivy, SpeechRecognition, Pyjnius, and Buildozer. It features a modern dark-mode user interface, a visually animated pulsing microphone button, native Android app control using Intents, and ChatGPT integration for fallback intelligence.

---

## 📂 Project Structure

```text
assistant/
├── main.py              # Main application source code (UI, Speech, JNI, Logic)
├── requirements.txt     # Python packages for development and Android packaging
├── buildozer.spec       # Buildozer specifications for compiling into Android APK
└── README.md            # Project technical documentation (this file)
```

---

## ⚙️ Core Architecture & OOP Design

The application is structured following object-oriented programming principles:
- **`AndroidMicrophone` (Speech-to-Text Source):** Inherits from `speech_recognition.AudioSource` and uses **Pyjnius** to record raw 16-bit PCM mono audio using Android's native `android.media.AudioRecord` API on a dedicated background thread. This bypasses the need for `PyAudio`, which is incompatible with Android due to compilation issues.
- **`TTSEngine` (Text-to-Speech Engine):** A platform-aware wrapper that instantiates Android's native `android.speech.tts.TextToSpeech` via Pyjnius when run on Android, and falls back to Python's `pyttsx3` when run on desktop.
- **`OpenAIClient` (Artificial Intelligence Fallback):** Sends queries to GPT-3.5-Turbo for commands that cannot be handled locally. It maintains a short chat log history of the last 10 messages for continuous conversational flow.
- **`VoiceAssistantApp` (Main Application & UI):** Controls Kivy UI render states, processes intent matching, handles threading for voice record loops, and requests Android permissions dynamically at startup.

---

## 📲 Android Permissions

Building an Android voice assistant requires specific permissions, which are declared in `buildozer.spec` under `android.permissions` and requested at runtime:

1. **Microphone (`RECORD_AUDIO`):**
   - **Why:** Allows the application to access the device's physical microphone.
   - **Implementation:** Declared in `buildozer.spec` and requested dynamically at application launch using Kivy's `android.permissions` API.
2. **Internet (`INTERNET`):**
   - **Why:** Needed to access Google Speech recognition APIs (transcribing Speech-to-Text), query OpenAI ChatGPT, and launch web search queries.
   - **Implementation:** Declared in `buildozer.spec`. This is a normal-tier permission granted automatically at installation.
3. **Foreground Service (`FOREGROUND_SERVICE`):**
   - **Why:** Allows the voice recognition threads to run without being abruptly terminated by Android's strict battery optimizer or memory manager.
   - **Implementation:** Enabled in `buildozer.spec` via `android.foreground_service = true`.

---

## 🛠️ Local Development & Desktop Testing

Before packaging the application for Android, you can run and test it on your local desktop (Windows, macOS, Linux):

### 1. Prerequisite Installations
Make sure you have Python 3 installed. Run the following command to install the required libraries:
```bash
pip install -r requirements.txt
```
*Note: PyAudio is required on desktops to record microphone input. If `pip` fails to install PyAudio, install it via your OS package manager:*
- **macOS:** `brew install portaudio && pip install pyaudio`
- **Linux (Ubuntu/Debian):** `sudo apt-get install python3-pyaudio`
- **Windows:** Download precompiled wheels from PyPI (installed automatically via `pip`).

### 2. Run the App
```bash
python main.py
```
Press the circular **🎤 (Microphone)** button to toggle speech recognition, or type command strings directly in the input box at the bottom.

---

## 📦 Android Compilation & Deployment (Step-by-Step)

Because Buildozer requires a Linux environment to compile Python into Android binaries, you must compile the application using **Linux (Ubuntu/Debian)** or **Windows Subsystem for Linux (WSL)**.

### Step 1: Install System Dependencies
In your Linux terminal, run the following commands to install build tools, JDK, and SDK components:
```bash
sudo apt update
sudo apt install -y git zip unzip openai python3-pip autoconf libtool pkg-config zlib1g-dev libncurses5-dev libssl-dev cmake
sudo apt install -y openjdk-17-jdk openjdk-17-jre
```

### Step 2: Install Buildozer
Install Buildozer globally using pip:
```bash
pip3 install --user --upgrade buildozer
```
Ensure your user binaries path is in your environment PATH:
```bash
export PATH=$PATH:~/.local/bin
```

### Step 3: Configure your OpenAI API Key (Optional)
To use ChatGPT integration, open settings using the ⚙️ icon at the top of the Kivy UI when running the app, paste your API Key, and save. This writes to the device's internal storage folder at `/data/user/0/org.assistant.voiceassistant/files/config.json`.

Alternatively, edit `config.json` before compiling to include your key:
```json
{
  "openai_api_key": "your-openai-api-key-here"
}
```

### Step 4: Compile and Deploy the APK
Connect your Android phone to your computer via USB, enable **USB Debugging** (in Developer Options), and run:
```bash
buildozer android debug deploy run
```
This command will:
1. Download the Android SDK & NDK automatically.
2. Cross-compile Python, Kivy, SpeechRecognition, Pyjnius, and other libraries for Android architectures (`arm64-v8a` and `armeabi-v7a`).
3. Package the files into a debug APK (`.apk`).
4. Install the application on your connected Android device.
5. Launch the application.

---

## 🗣️ Voice Commands & Intents

The voice assistant will listen and react to the following voice commands:

| Command | Action | Platform Behavior |
| :--- | :--- | :--- |
| **"Open YouTube"** | Launches YouTube | Natively opens YouTube app on Android; fallback to browser on desktop. |
| **"Open WhatsApp"** | Launches WhatsApp | Natively opens WhatsApp app on Android; fallback to browser on desktop. |
| **"Open Instagram"** | Launches Instagram | Natively opens Instagram app on Android; fallback to browser on desktop. |
| **"Open Chrome"** | Launches Chrome | Natively opens Chrome browser on Android; fallback to default browser on desktop. |
| **"Open Settings"** | Launches Settings | Natively opens system Settings on Android; control panel on desktop. |
| **"Search Google for [query]"** | Performs Google search | Launches browser with Google query results. |
| **"What is the time"** | Speaks current time | Computes local time and speaks it out loud. |
| **"What is today's date"** | Speaks today's date | Computes local date and speaks it out loud. |
| **Any other query** | ChatGPT interaction | Falls back to ChatGPT API using your configured OpenAI key. |

---

## 🔍 Debugging & Error Logging

If the application crashes, behaves unexpectedly, or fails to hear voice commands on your Android phone, you can inspect real-time log outputs using `adb` (Android Debug Bridge):

1. **View Logs:**
   Filter logs to only show Python print statements and assistant errors:
   ```bash
   buildozer android logcat | grep -i "python"
   ```
   Or use direct adb command:
   ```bash
   adb logcat -s python VoiceAssistant
   ```
2. **Error Recovery & Fail-safes:**
   - **Microphone failures:** If the recording fails due to lack of permission or hardware access, the UI status bar turns Red showing `"Error"` and prints an error message. It will not crash the application.
   - **SpeechRecognition Offline:** If the user has no internet access, the SpeechRecognition library raises `RequestError`. The assistant logs this, updates the UI chat logs, and announces: `"Speech service is currently offline. Try typing your command."`
   - **OpenAI Key Missing:** If the user sends a general query without configuring the OpenAI API key, the assistant will friendly remind them: `"I don't know how to do that yet. Please set up your API key for advanced AI queries."`
