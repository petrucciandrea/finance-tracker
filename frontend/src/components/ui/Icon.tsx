import type { SVGProps } from 'react'

// Small, dependency-free icon set (Heroicons-style outline paths, MIT-equivalent
// simple shapes) — avoids pulling in a full icon package for three glyphs.
type IconProps = SVGProps<SVGSVGElement>

function BaseIcon({ children, ...props }: IconProps) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      className="h-4 w-4"
      {...props}
    >
      {children}
    </svg>
  )
}

export function PlusIcon(props: IconProps) {
  return (
    <BaseIcon {...props}>
      <path d="M12 5v14M5 12h14" />
    </BaseIcon>
  )
}

export function PencilIcon(props: IconProps) {
  return (
    <BaseIcon {...props}>
      <path d="M16.862 4.487a1.875 1.875 0 1 1 2.652 2.652L7.5 19.153l-4 1 1-4L16.862 4.487Z" />
    </BaseIcon>
  )
}

export function TrashIcon(props: IconProps) {
  return (
    <BaseIcon {...props}>
      <path d="M4 7h16M9 7V4h6v3m-8 0 .867 12.142A2 2 0 0 0 9.862 21h4.276a2 2 0 0 0 1.995-1.858L17 7" />
    </BaseIcon>
  )
}

export function GripVerticalIcon(props: IconProps) {
  return (
    <BaseIcon {...props} strokeWidth={0} fill="currentColor" stroke="none">
      <circle cx="9" cy="5" r="1.5" />
      <circle cx="9" cy="12" r="1.5" />
      <circle cx="9" cy="19" r="1.5" />
      <circle cx="15" cy="5" r="1.5" />
      <circle cx="15" cy="12" r="1.5" />
      <circle cx="15" cy="19" r="1.5" />
    </BaseIcon>
  )
}
