import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Ссылка внутри текста: подчёркнута и видна с клавиатуры. */
export const textLinkClass =
  'rounded text-ring underline underline-offset-4 focus-visible:outline-2 focus-visible:outline-ring';
