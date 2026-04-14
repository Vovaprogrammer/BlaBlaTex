export const useTheme = () => {
  const toggleTheme = () => {
    const root = document.documentElement;

    root.classList.toggle("dark");
  };

  return {
    theme: document.documentElement.classList.contains("dark") ? "dark" : "light",
    toggleTheme,
  };
};