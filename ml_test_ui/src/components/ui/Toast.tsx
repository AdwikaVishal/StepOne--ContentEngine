/**
 * Toast notification system using sonner.
 * Import { toast } from './Toast' and call toast.success(), toast.error(), etc.
 */
import { Toaster, toast as sonnerToast } from 'sonner'

export function ToastProvider() {
  return (
    <Toaster
      position="bottom-right"
      toastOptions={{
        style: {
          background: 'var(--s2)',
          border: '1px solid var(--b1)',
          color: 'var(--t1)',
          borderRadius: '10px',
          fontSize: '13px',
          fontFamily: 'Inter, system-ui, sans-serif',
        },
        className: 'ce-toast',
      }}
      richColors
    />
  )
}

export const toast = {
  success: (msg: string, desc?: string) => sonnerToast.success(msg, { description: desc }),
  error:   (msg: string, desc?: string) => sonnerToast.error(msg,   { description: desc }),
  info:    (msg: string, desc?: string) => sonnerToast.info(msg,    { description: desc }),
  warning: (msg: string, desc?: string) => sonnerToast.warning(msg, { description: desc }),
  loading: (msg: string)                => sonnerToast.loading(msg),
  dismiss: (id?: string | number)       => sonnerToast.dismiss(id),
  promise: <T,>(p: Promise<T>, msgs: { loading: string; success: string; error: string }) =>
    sonnerToast.promise(p, msgs),
}
