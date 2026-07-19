// Mirrors backend app/otp.py DEFAULT_PATTERN.
const CODE_PATTERN = /(?<![\d.-])(\d{4,8})(?![\d.-])/;

export function extractCode(body: string): string | null {
  const match = CODE_PATTERN.exec(body);
  return match ? match[1] : null;
}
