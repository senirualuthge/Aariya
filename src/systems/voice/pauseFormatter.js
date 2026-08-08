export function addPauses(text, mode = "airiyaPersonality") {
    let formattedText = text;

    if (mode === "shyFlirty") {
        formattedText = formattedText
            .replace(/(^|\. )/g, "$1<break time='300'/>")
            .replace(/(cute|nice|sweet)/gi, "<break time='200'/>$1");
    } else if (mode === "flirtyMode") {
        formattedText = formattedText.replace(/\./g, ". <break time='400'/>");
    } else if (mode === "extraExcited") {
        // Less pauses for excited, maybe just breaths
        formattedText = formattedText.replace(/\./g, ". <break time='100'/>");
    } else {
        // Default (Calm)
        formattedText = formattedText.replace(/\./g, ". <break time='250'/>");
    }

    // "Fake Breaths" - Max 1 per message to avoid annoyance
    // Only if text is long enough
    if (text.length > 50 && !formattedText.includes("Mm <break")) {
        const fillers = [
            "Mm <break time='200'/> ", 
            "You know <break time='150'/> ",
            "Uh <break time='200'/> "
        ];
        // 30% chance to add a filler at start if not already starting with one
        if (Math.random() < 0.3) {
            const filler = fillers[Math.floor(Math.random() * fillers.length)];
            formattedText = filler + formattedText;
        }
    }

    return formattedText;
}
