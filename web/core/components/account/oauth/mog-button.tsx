import { FC } from "react";
import { useSearchParams } from "next/navigation";
import { useTheme } from "next-themes";
// helpers
import { API_BASE_URL } from "@plane/constants";

export type MogOAuthButtonProps = {
  text: string;
};

export const MogOAuthButton: FC<MogOAuthButtonProps> = (props) => {
  const searchParams = useSearchParams();
  const nextPath = searchParams.get("next_path");
  const { text } = props;
  // hooks
  const { resolvedTheme } = useTheme();

  const handleSignIn = () => {
    window.location.assign(`${API_BASE_URL}/auth/mog/${nextPath ? `?next_path=${nextPath}` : ``}`);
  };

  return (
    <button
      className={`flex h-[42px] w-full items-center justify-center gap-2 rounded border px-2 text-sm font-medium text-custom-text-100 duration-300 bg-onboarding-background-200 hover:bg-onboarding-background-300 ${
        resolvedTheme === "dark" ? "border-[#43484F]" : "border-[#D9E4FF]"
      }`}
      onClick={handleSignIn}
    >
      <span className="flex h-5 w-5 items-center justify-center rounded bg-[#79c471] text-xs font-semibold text-black">
        M
      </span>
      {text}
    </button>
  );
};
