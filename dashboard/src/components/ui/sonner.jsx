import { Toaster as Sonner } from "sonner";
import { CheckCircle2, Info, AlertTriangle, XCircle, Loader2 } from "lucide-react"

const Toaster = ({
  ...props
}) => {
  return (
    <Sonner
      theme="dark"
      className="toaster group"
      icons={{
        success: <CheckCircle2 className="w-4 h-4" />,
        info: <Info className="w-4 h-4" />,
        warning: <AlertTriangle className="w-4 h-4" />,
        error: <XCircle className="w-4 h-4" />,
        loading: <Loader2 className="w-4 h-4 animate-spin" />,
      }}
      style={
        {
          "--normal-bg": "var(--popover)",
          "--normal-text": "var(--popover-foreground)",
          "--normal-border": "var(--border)",
          "--border-radius": "var(--radius)"
        }
      }
      toastOptions={{
        classNames: {
          toast: "cn-toast",
        },
      }}
      {...props} />
  );
}

export { Toaster }
