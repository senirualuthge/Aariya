const BREATHS = {
  comma: "<break time='120'/>",
  period: "<break time='320'/>",
  ellipsis: "<break time='450'/>",
  question: "<break time='220'/>",
  exclaim: "<break time='180'/>"
};

export function addBreaths(text) {
  return text
    .replace(/,/g, `, ${BREATHS.comma}`)
    .replace(/\.\.\./g, `... ${BREATHS.ellipsis}`)
    .replace(/\./g, `. ${BREATHS.period}`)
    .replace(/\?/g, `? ${BREATHS.question}`)
    .replace(/!/g, `! ${BREATHS.exclaim}`);
}
