interface DogIconProps extends React.SVGProps<SVGSVGElement> {
  disabled?: boolean;
}

const DogIcon = ({ disabled = false, stroke, ...props }: DogIconProps) => {
  const fillColor = disabled ? "#71717A" : (stroke || "#22A7AF");

  return (
    disabled ? (
      <svg xmlns="http://www.w3.org/2000/svg" width="24" height="18" viewBox="0 0 24 18" fill={fillColor}>
        <path d="M8 18H2V16H8V18Z"/>
        <path fill-rule="evenodd" clip-rule="evenodd" d="M20 2H22V6H24V10H20V14H24V16H14V14H2V16H0V8H2V6H8V10H10V12H16V6H14V10H12V8H10V2H12V0H20V2ZM18 6H20V4H18V6Z"/>
      </svg>
    ) : (
      <svg xmlns="http://www.w3.org/2000/svg" width="24" height="20" viewBox="0 0 24 20" fill={fillColor}>
        <path fill-rule="evenodd" clip-rule="evenodd" d="M11.0769 10.9091H16.6154V5.45455H14.7692V9.09091H12.9231V7.27273H11.0769V1.81818H12.9231V0H20.3077V1.81818H22.1538V5.45455H24V9.09091H20.3077V14.5455H18.4615V20H14.7692V16.3636H12.9231V14.5455H7.38462V16.3636H5.53846V20H1.84615V10.9091H3.69231V9.09091H11.0769V10.9091ZM18.4615 5.45455H20.3077V3.63636H18.4615V5.45455Z"/>
        <path d="M1.84615 10.9091H0V7.27273H1.84615V10.9091Z"/>
        <path d="M3.69231 7.27273H1.84615V5.45455H3.69231V7.27273Z"/>
        <path d="M5.53846 5.45455H3.69231V3.63636H5.53846V5.45455Z"/>
      </svg>
    )
  )
}

export default DogIcon;