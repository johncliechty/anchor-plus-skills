import fs from 'fs';

if (fs.existsSync('package-lock.json')) {
    const lockfile = JSON.parse(fs.readFileSync('package-lock.json', 'utf8'));
    let hasError = false;
    
    const packages = lockfile.packages || {};
    for (const [pkg, details] of Object.entries(packages)) {
        if (details.hasInstallScript || details.scripts) {
            console.error(`Package ${pkg} has a lifecycle install script.`);
            hasError = true;
        }
        if (pkg.includes('node-gyp') || (details.dependencies && details.dependencies['node-gyp'])) {
            console.error(`Package ${pkg} depends on node-gyp.`);
            hasError = true;
        }
    }

    if (hasError) {
        console.error("Lockfile lint failed. Pure-JS dependency policy violated.");
        process.exit(1);
    } else {
        console.log("Lockfile lint passed.");
    }
} else {
    console.log("No package-lock.json found. Skipping lockfile lint.");
}
