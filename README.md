# FLARE
Fast Licensing Accident Response Engine

## Home-screen icon (FLARE Buddy)

Streamlit serves its own page, so "Add to Home Screen" on the app address shows Streamlit's logo.
The `docs/` folder is a small launcher page with the FLARE Buddy icon and the name "FLARE" that
opens the app (https://flare-pwr.streamlit.app) in a full-window frame. It is published with GitHub Pages:

1. On github.com: **Settings → Pages → Build and deployment → Source: Deploy from a branch**,
   branch `main`, folder `/docs`, **Save**.
2. After a minute or two, open **https://smsrpm.github.io/FLARE/** on the phone and use
   **Share → Add to Home Screen** (iPhone) or **⋮ → Add to Home screen** (Android).
3. Delete any older shortcut first: iOS never updates the icon of an existing shortcut.

The icons are built from `flare-pwr/Icons/FLAREBUDDY.png`, which is also the app's browser-tab icon.
If the app address changes, edit the two addresses in `docs/index.html`.
