// Host-side ExtendScript. Deliberately empty of logic: every command the bridge
// runs carries its own helpers (skleyka/jsx/*.jsx), so changing what the bridge
// can do never means re-signing this panel or restarting Premiere.
function skleykaPing() {
    return "pong";
}
