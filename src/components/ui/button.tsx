"use client";

import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-[13px] font-medium transition-colors disabled:pointer-events-none disabled:opacity-45 [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default: "bg-rail text-ink hover:bg-rail/90 font-semibold",
        outline: "border border-line-strong bg-panel-2 text-text hover:bg-panel-3 hover:border-rail/50",
        ghost: "text-muted hover:bg-panel-2 hover:text-text",
        clear: "bg-clear/12 text-clear border border-clear/35 hover:bg-clear/20",
        stop: "bg-stop/12 text-stop border border-stop/35 hover:bg-stop/20",
        quiet: "text-dim hover:text-text",
      },
      size: {
        default: "h-11 px-3.5 md:h-9",
        sm: "h-10 px-2.5 text-[12px] md:h-7",
        lg: "h-11 px-5 text-sm",
        icon: "size-11 md:size-8",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return <Comp className={cn(buttonVariants({ variant, size, className }))} ref={ref} {...props} />;
  },
);
Button.displayName = "Button";

export { buttonVariants };
