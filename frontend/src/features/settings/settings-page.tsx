import { DeleteAccount } from './delete-account';
import { LlmKeySettings } from './llm-key-settings';
import { PersonalTokens } from './personal-tokens';

export function SettingsPage() {
  return (
    <div className="space-y-6">
      <h1 className="text-3xl font-bold sm:text-4xl">Настройки</h1>
      <LlmKeySettings />
      <PersonalTokens />
      <DeleteAccount />
    </div>
  );
}
