================================================================================
  FLARE -- Fast Licensing Accident Response Engine
  PWR / SMR Reactor Safety Analysis Tool
  Installation & Quick-Start Guide  |  Revision 0 -- May 2026
  Robert P. Martin
================================================================================


CONTENTS
--------------------------------------------------------------------------------

  1.  System Requirements
  2.  Installation
      2.1  Install Python
      2.2  Create the Virtual Environment
      2.3  Install Required Packages
      2.4  Extract the FLARE Package
      2.5  Verify the Installation
  3.  Day-to-Day Launch
  4.  Installation Checklist
  5.  Troubleshooting


================================================================================
  1.  SYSTEM REQUIREMENTS
================================================================================

  OS          Windows 10 or Windows 11 (64-bit)
  Python      3.11 or 3.12 -- from python.org, must be added to PATH
  RAM         4 GB minimum; 8 GB recommended for batch UA runs
  Disk        ~500 MB for the virtual environment; ~50 MB per run directory
  Network     Required only for AI narrative (Anthropic API) and ngrok


================================================================================
  2.  INSTALLATION
================================================================================

  Complete steps 2.1 through 2.5 once on a new machine, in order.


  2.1  INSTALL PYTHON
  --------------------------------------------------------------------------------

  Download and install Python 3.11 or 3.12 from:

    https://www.python.org/downloads/

  IMPORTANT: During installation, check the box "Add Python to PATH"
  before clicking Install Now. Without this, all subsequent commands fail.

  Verify from PowerShell once installation is complete:

    python --version

  Expected output: Python 3.11.x  or  Python 3.12.x


  2.2  CREATE THE VIRTUAL ENVIRONMENT
  --------------------------------------------------------------------------------

  Open PowerShell and run:

    cd C:\Users\%USERNAME%
    python -m venv flare_env

  This creates an isolated Python environment at C:\Users\<you>\flare_env.
  The environment only needs to be created once -- it persists between sessions.

  NOTE: The launch_flare.bat launcher activates the flare_env environment
  automatically. Placing it at C:\Users\<you>\flare_env (the default
  above) is recommended.


  2.3  INSTALL REQUIRED PACKAGES
  --------------------------------------------------------------------------------

  Activate the new environment, then install all packages with one command:

    flare_env\Scripts\activate
    python -m pip install numpy pandas scipy openpyxl matplotlib XSteamPython plotly streamlit reportlab python-docx anthropic

  Packages installed:

    numpy / scipy       Numerical computing and statistical functions
    pandas              Data manipulation and CSV / Excel I/O
    openpyxl            Reading and writing Excel (.xlsx) input/output decks
    matplotlib          Figure generation
    XSteamPython        IAPWS-IF97 water and steam properties
    plotly              Interactive charts in the Streamlit UI
    streamlit           Web UI framework
    reportlab           PDF report generation
    python-docx         Word document generation
    anthropic           Anthropic Claude API client for AI narrative features

  Verify the key packages installed correctly:

    python -c "import openpyxl; import streamlit; import XSteamPython; print('OK')"

  Expected output: OK


  2.4  EXTRACT THE FLARE PACKAGE
  --------------------------------------------------------------------------------

  Unzip the FLARE package to a folder of your choice, for example:

    C:\Users\<you>\Documents\FLARE\

  The folder must contain all of the following:

    Python modules
      flare_home.py, flare_sim.py, flare_ui.py, flare_ua.py, flare_risk.py
      flare_sim_batch_worker.py, flare_ua_worker.py, flare_risk_worker.py
      flare_model_editor.py, flare_analyzer.py

    Launcher scripts
      launch_flare.bat
      start_streamlit.ps1, start_ngrok.ps1

    Input decks
      Case*_in.xlsx  (one workbook per case)

  NOTE: Avoid placing the FLARE folder inside an actively-synced OneDrive
  location. The durable worker processes write many small JSON status files
  rapidly, which can cause transient file-lock conflicts with OneDrive.


  2.5  VERIFY THE INSTALLATION
  --------------------------------------------------------------------------------

  Navigate to the FLARE folder and run the steady-state verification case:

    cd "C:\Users\<you>\Documents\FLARE"
    flare_env\Scripts\activate
    python flare_sim.py CaseSteadyState

  The run is successful if these output files appear in the FLARE folder:

    CaseSteadyState_out.xlsx
    CaseSteadyState_out.csv

  Then launch the Streamlit UI to confirm the web interface starts correctly:

    python -m streamlit run flare_home.py

  FLARE Home should open at http://localhost:8501. Press Ctrl+C to stop.

  NOTE: If PowerShell blocks any .ps1 script with a security error, run
  the following once and then retry:

    Unblock-File -Path ".\start_streamlit.ps1"
    Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser


================================================================================
  3.  DAY-TO-DAY LAUNCH
================================================================================

  QUICK LAUNCH (RECOMMENDED)
  --------------------------------------------------------------------------------

  Double-click launch_flare.bat in the FLARE folder. This opens two windows:

    Window 1 -- activates flare_env and starts Streamlit on port 8501
    Window 2 -- starts an ngrok tunnel for remote / mobile browser access

  FLARE opens at http://localhost:8501. The ngrok public URL printed in
  Window 2 can be used from any device on any network.

  MANUAL LAUNCH
  --------------------------------------------------------------------------------

  If you prefer to activate the environment manually each session:

    cd "C:\Users\<you>\Documents\FLARE"
    .\start_streamlit.ps1
    python -m streamlit run flare_home.py

  The start_streamlit.ps1 script activates the flare_env environment and
  starts Streamlit on port 8501.


================================================================================
  4.  INSTALLATION CHECKLIST
================================================================================

  Step  Action                                                           Done
  ----  ---------------------------------------------------------------  ----
  2.1   Python 3.11 or 3.12 installed                                    [ ]
  2.1   "Add Python to PATH" checked during installation                 [ ]
  2.2   flare_env created at C:\Users\<you>\flare_env                    [ ]
  2.3   All ten packages installed without errors                        [ ]
  2.3   import openpyxl / streamlit / XSteamPython check returns OK      [ ]
  2.4   FLARE folder extracted with all .py, .bat, .ps1, and .xlsx files [ ]
  2.5   CaseSteadyState produces _out.xlsx and _out.csv                  [ ]
  2.5   Streamlit UI opens at http://localhost:8501                      [ ]
  3     launch_flare.bat opens both PowerShell windows successfully      [ ]
  --    PowerShell execution policy set if required                      [ ]


================================================================================
  5.  TROUBLESHOOTING
================================================================================

  PowerShell blocks .ps1 scripts
    Run: Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

  python not recognised after install
    Re-run the Python installer; check "Add Python to PATH" before Install Now.

  python not found after activation
    Re-run start_streamlit.ps1; confirm flare_env\Scripts\python.exe exists.

  ModuleNotFoundError on startup
    Re-run the pip install command from Step 2.3 with flare_env active.

  CaseSteadyState produces no output files
    Check the console for a traceback. Most common cause: missing package.

  Streamlit port 8501 already in use
    Close the existing Streamlit window, or use:
    python -m streamlit run flare_home.py --server.port 8502

  launch_flare.bat opens but Streamlit fails immediately
    Run start_streamlit.ps1 manually to see the full error output.

  ngrok tunnel not working
    Confirm ngrok is installed and on PATH. Edit the domain in start_ngrok.ps1
    to match your ngrok account.

  AV / EDR flags flare_ua.py or flare_risk.py
    False positive. The files call api.anthropic.com with an API key, which
    heuristic scanners can flag as data exfiltration. Whitelist the file or
    the api.anthropic.com domain in your security tool.

================================================================================
