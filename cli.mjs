// cli.mjs - Aariya Terminal Chat Interface (Improved with Dynamic Engine)
import readline from 'readline';
import { handleMessage, analyzeUserEmotion, setGeneratorPersonality } from './src/systems/aiEngine.js';
import { PERSONALITY_PRESETS } from './src/systems/personalityPresets.js';
import chalk from 'chalk';

const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
    prompt: chalk.bold.magenta('You: ')
});

let currentPersonality = 'aria';

console.log(chalk.bold.cyan('\n=== AARIYA AI COMPANION (NATURAL DIALOGUE) ==='));
console.log(chalk.gray('Type "exit" or "quit" to end the session.\n'));

function aariyaSpeak(text) {
    // Terminal styling based on personality
    let styledText = text;
    if (currentPersonality === 'bubbly') styledText = chalk.yellow(text);
    else if (currentPersonality === 'flirty') styledText = chalk.magenta(text);
    else if (currentPersonality === 'cutie') styledText = chalk.rgb(255, 182, 193)(text); // Soft pink
    else if (currentPersonality === 'arrogant') styledText = chalk.blue(text);
    else styledText = chalk.white(text);

    console.log(`${chalk.bold.cyan('Aariya:')} ${styledText}\n`);
}

// Initial Greeting Logic
(async () => {
    const { text } = await handleMessage("cli_user", "hello");
    aariyaSpeak(text);
    rl.prompt();
})();

rl.on('line', async (line) => {
    const input = line.trim();
    const lower = input.toLowerCase();

    if (lower === 'exit' || lower === 'quit') {
        console.log(chalk.cyan('\nAariya: Goodbye! I\'ll be waiting for you... 💕'));
        process.exit(0);
    }

    if (!input) {
        rl.prompt();
        return;
    }

    // 1. Emotion analysis & Personality Sync
    const { detected, emotion } = analyzeUserEmotion(input);
    if (detected) {
        if (emotion === 'angry') currentPersonality = 'arrogant';
        else if (emotion === 'happy') currentPersonality = 'bubbly';
        setGeneratorPersonality(currentPersonality);
    }

    // 2. Override check
    if (lower.includes("bubbly")) currentPersonality = 'bubbly';
    else if (lower.includes("serious")) currentPersonality = 'calm';
    else if (lower.includes("cute")) currentPersonality = 'cutie';
    else if (lower.includes("flirt")) currentPersonality = 'flirty';
    setGeneratorPersonality(currentPersonality);

    // 3. Handle Message (Now Dynamic)
    try {
        const { text } = await handleMessage("cli_user", input, []);
        aariyaSpeak(text);
    } catch (err) {
        console.error(chalk.red('Error:'), err.message);
    }

    rl.prompt();
}).on('close', () => {
    console.log(chalk.cyan('\nGoodbye!'));
    process.exit(0);
});
