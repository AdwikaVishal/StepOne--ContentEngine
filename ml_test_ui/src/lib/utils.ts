export function cn(...inputs: Array<any>): string {
  return inputs.filter(Boolean).join(" ");
}

export default cn;
