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
- An Apple Developer account to sign the app. A friend's works: see step 3.

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

## 3. Sign it with your friend's developer account

Your friend adds you to their team once:

1. In [App Store Connect](https://appstoreconnect.apple.com) → **Users and Access**, they invite your Apple ID with the **App Manager** role (or Admin), and tick **Access to Certificates, Identifiers & Profiles**.
2. You accept the email invitation.

Then on your Mac:

1. **Xcode → Settings → Accounts**: add your Apple ID. Your friend's team appears under it.
2. In the project navigator, click **App**, then the **App** target → **Signing & Capabilities**.
3. Tick **Automatically manage signing** and choose your friend's team under **Team**.
4. **Bundle Identifier** is `se.osterbergdesign.matkoll`. If Xcode says it's taken, change the end to something unique, e.g. `se.osterbergdesign.matkoll.home`.
5. **HealthKit** should be listed among the capabilities. If it isn't, click **+ Capability** and add **HealthKit**.

## 4. Put it on your phones

The simplest way for a household is to install straight from the Mac. Each phone needs this once:

1. On the iPhone: **Settings → Privacy & Security → Developer Mode** → on (the phone restarts). The option appears after the phone has been connected to Xcode once.
2. Connect the iPhone to the Mac with a cable and tap **Trust** on the phone.
3. In Xcode's toolbar, pick the iPhone as the run destination and press **Run** (▶).
4. If the phone says the developer isn't trusted: **Settings → General → VPN & Device Management** → tap the developer → **Trust**.

Apps installed this way keep working for about a year, until the signing profile expires. Then press Run again.

### Or through TestFlight

Better if family members aren't near the Mac. In Xcode: **Product → Archive**, then **Distribute App → TestFlight & App Store**. The app needs a record in App Store Connect first (**Apps → + → New App**, with the same bundle identifier). Internal testers must be members of your friend's team; each TestFlight build lasts 90 days. `npm run ios:sync` raises the build number automatically, which TestFlight requires for every upload.

## Updating the app

Most changes arrive through the server (`pct exec <id> -- matkoll-update`) and need nothing here. When this folder changes:

```bash
cd LoCal-Tracker
git pull
cd ios-app
npm install
npm run ios:sync
```

Then press **Run** in Xcode (or archive a new TestFlight build).

## Troubleshooting

- **"Can't reach Matkoll"**: the phone must be on your home network (or Tailscale). Check the address under **You → Change server**, and that the container is running.
- **The app asks for Local Network access**: allow it; that's how it reaches your server on the home network.
- **Barcode scanner says camera access is off**: **Settings → Matkoll → Camera**.
- **Nothing appears in Apple Health**: **Health app → Sharing → Apps → Matkoll** and allow writing for Dietary Energy and the nutrients.
- **Signing errors about HealthKit**: your Apple ID needs the certificates access from step 3, or your friend can enable HealthKit for the bundle identifier at developer.apple.com → Identifiers.
