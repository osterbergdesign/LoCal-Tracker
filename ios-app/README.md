# Matkoll for iPhone

A native iPhone app around your Matkoll server. The screens come from the server, so they update whenever you run `matkoll-update`; the app adds what a web page can't do:

- **Apple's barcode scanner**, fast and working over plain `http://`
- **Apple Health**: your daily calories, protein, carbs, fat and fibre are saved to the Health app (turn it on under **You → iPhone app**)
- A real app icon, full screen, no browser bar

On first launch the app asks for your server's address, e.g. `http://192.168.1.77:8080`. Change it later under **You → Change server**.

You only need to rebuild the app when something in this `ios-app` folder changes.

## What you need

- A Mac with **Xcode 26** or newer (free from the App Store). Open it once after installing so it can finish setting up.
- **Node.js 22** or newer: download the LTS installer from [nodejs.org](https://nodejs.org).
- An Apple ID. Your normal one works (free); a paid Apple Developer account ($99/year) only removes the weekly reinstall. See step 3.

## 1. Get the code

In Terminal:

```bash
git clone https://github.com/osterbergdesign/LoCal-Tracker.git
cd LoCal-Tracker/ios-app
npm install
npm run ios:create
```

`ios:create` generates the Xcode project in `ios/` and applies Matkoll's settings (camera and Health permission texts, Apple Health entitlement, local network access, icon). If your Mac asks to install developer tools when you run `git`, accept and run the command again.

## 2. Open it in Xcode

```bash
npm run ios:open
```

## 3. Sign it

### With your own Apple ID (free)

1. **Xcode → Settings → Accounts**: click **+** and sign in with your Apple ID. It shows up as "Your Name (Personal Team)".
2. In the project navigator, click **App**, then the **App** target → **Signing & Capabilities**.
3. Tick **Automatically manage signing** and pick your **Personal Team**.
4. Change **Bundle Identifier** to something only you use, e.g. `se.osterbergdesign.matkoll.yourname`.
5. If Xcode shows a signing error that mentions **HealthKit**, your free account can't sign Apple Health. Build without it and everything else still works:
   ```bash
   HEALTH=0 npm run ios:sync
   ```

What a free Apple ID means:

- **The app stops opening after 7 days.** Connect the phone (or have it on the same Wi-Fi, see below) and press **Run** again. Nothing is lost: your data lives on your server.
- At most 3 apps installed this way per phone.

### With a paid developer account

Signing lasts a year instead of 7 days, and TestFlight becomes possible. If it's someone else's account, they invite your Apple ID in [App Store Connect](https://appstoreconnect.apple.com) → **Users and Access** with the **App Manager** role and **Access to Certificates, Identifiers & Profiles** ticked. Then pick their team in step 3 instead of your Personal Team.

## 4. Put it on your phone

1. Connect the iPhone to the Mac with a cable and tap **Trust** on the phone.
2. In Xcode's toolbar, pick the iPhone as the run destination and press **Run** (▶).
3. On the iPhone: **Settings → Privacy & Security → Developer Mode** → on (the phone restarts), then press **Run** again.
4. The first time, the phone says the developer isn't trusted: **Settings → General → VPN & Device Management** → tap your Apple ID → **Trust**.

**Reinstalling without a cable:** in Xcode, **Window → Devices and Simulators**, select the phone and tick **Connect via network**. From then on, when the phone and Mac are on the same Wi-Fi, pressing **Run** reinstalls it wirelessly. With a free Apple ID, doing this once a week keeps the app working.

Each family phone gets the same treatment once; with a free Apple ID, every phone needs the weekly Run.

## Sideloading tools (no weekly Mac visit)

[SideStore](https://sidestore.io) and [AltStore](https://altstore.io) install apps signed with your own free Apple ID, like Xcode does, but refresh them in the background so the 7-day limit takes care of itself (AltStore refreshes over Wi-Fi from AltServer on your Mac; SideStore refreshes on the phone itself). They install `.ipa` files, which you build on the Mac:

```bash
./build-ipa.sh
```

That writes `build/Matkoll.ipa`, built without Apple Health because these tools can't sign it. AirDrop the file to your phone and open it with SideStore or AltStore. Follow their setup guides first; they need a one-time setup with your Mac. The 3-app limit counts the sideloading tool itself.

Apple's EU alternative app marketplaces (AltStore PAL and others) don't help here: apps in them must still be published by a paid developer account.

### Or through TestFlight (paid account only)

In Xcode: **Product → Archive**, then **Distribute App → TestFlight & App Store**. The app needs a record in App Store Connect first (**Apps → + → New App**, with the same bundle identifier). Internal testers must be members of the developer team; each TestFlight build lasts 90 days. `npm run ios:sync` raises the build number automatically, which TestFlight requires for every upload.

## Updating the app

Most changes arrive through the server (`pct exec <id> -- matkoll-update`) and need nothing here. When this folder changes:

```bash
cd LoCal-Tracker
git pull
cd ios-app
npm install
npm run ios:sync          # or: HEALTH=0 npm run ios:sync
```

Then press **Run** in Xcode (or run `./build-ipa.sh` again for SideStore/AltStore).

## Troubleshooting

- **"Can't reach Matkoll"**: the phone must be on your home network (or Tailscale). Check the address under **You → Change server**, and that the container is running.
- **The app asks for Local Network access**: allow it; that's how it reaches your server on the home network.
- **Barcode scanner says camera access is off**: **Settings → Matkoll → Camera**.
- **Nothing appears in Apple Health**: **Health app → Sharing → Apps → Matkoll** and allow writing for Dietary Energy and the nutrients.
- **Signing errors about HealthKit**: with a free Apple ID, run `HEALTH=0 npm run ios:sync` and press Run again. With a paid team, your Apple ID needs the certificates access from step 3.
- **"Maximum number of apps" error**: a free Apple ID allows 3 sideloaded apps per phone. Delete one you don't use.
