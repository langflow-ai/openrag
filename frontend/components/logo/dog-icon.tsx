interface DogIconProps extends React.SVGProps<SVGSVGElement> {
  disabled?: boolean;
}

const DogIcon = ({ disabled = false, stroke, ...props }: DogIconProps) => {
  const fillColor = disabled ? "#71717A" : stroke || "#773EFF";

  // CSS for the stepped animation states
  const animationCSS = `
    .state1 { animation: showDogState1 600ms infinite; }
    .state2 { animation: showDogState2 600ms infinite; }
    .state3 { animation: showDogState3 600ms infinite; }
    .state4 { animation: showDogState4 600ms infinite; }
    
    @keyframes showDogState1 {
      0%, 24.99% { opacity: 1; }
      25%, 100% { opacity: 0; }
    }
    
    @keyframes showDogState2 {
      0%, 24.99% { opacity: 0; }
      25%, 49.99% { opacity: 1; }
      50%, 100% { opacity: 0; }
    }
    
    @keyframes showDogState3 {
      0%, 49.99% { opacity: 0; }
      50%, 74.99% { opacity: 1; }
      75%, 100% { opacity: 0; }
    }
    
    @keyframes showDogState4 {
      0%, 74.99% { opacity: 0; }
      75%, 100% { opacity: 1; }
    }
  `;

  return disabled ? (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="24"
      height="18"
      viewBox="0 0 24 18"
      fill={fillColor}
      {...props}
    >
      <path d="M8 18H2V16H8V18Z" />
      <path
        fillRule="evenodd"
        clipRule="evenodd"
        d="M20 2H22V6H24V10H20V14H24V16H14V14H2V16H0V8H2V6H8V10H10V12H16V6H14V10H12V8H10V2H12V0H20V2ZM18 6H20V4H18V6Z"
      />
    </svg>
  ) : (
    <svg
      width="105"
      height="77"
      viewBox="0 0 105 77"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <defs>
        <style dangerouslySetInnerHTML={{ __html: animationCSS }} />
      </defs>

      {/* State 1 - Add 14px left padding to align with state 3 */}
      <g className="state1">
        <path
          fillRule="evenodd"
          clipRule="evenodd"
          d="M56 42H77V21H70V35H63V28H56V7H63V0H91V7H98V21H105V35H91V56H84V77H70V63H63V56H42V63H35V77H21V42H28V35H56V42ZM84 21H91V14H84V21Z"
          fill={fillColor}
        />
        <path d="M21 42H14V28H21V42Z" fill={fillColor} />
        <path d="M28 28H21V21H28V28Z" fill={fillColor} />
        <path d="M35 21H28V14H35V21Z" fill={fillColor} />
      </g>

      {/* State 2 - Add 14px left padding to align with state 3 */}
      <g className="state2">
        <path
          fillRule="evenodd"
          clipRule="evenodd"
          d="M56 42H77V21H70V35H63V28H56V7H63V0H91V7H98V21H105V35H91V56H84V77H70V63H63V56H42V63H35V77H21V42H28V35H56V42ZM84 21H91V14H84V21Z"
          fill={fillColor}
        />
        <path d="M21 42H14V14H21V42Z" fill={fillColor} />
      </g>

      {/* State 3 - Already properly positioned */}
      <g className="state3">
        <path
          fillRule="evenodd"
          clipRule="evenodd"
          d="M56 42H77V21H70V35H63V28H56V7H63V0H91V7H98V21H105V35H91V56H84V77H70V63H63V56H42V63H35V77H21V42H28V35H56V42ZM84 21H91V14H84V21Z"
          fill={fillColor}
        />
        <path d="M21 42H14V28H21V42Z" fill={fillColor} />
        <path d="M14 28H7V21H14V28Z" fill={fillColor} />
        <path d="M7 21H0V14H7V21Z" fill={fillColor} />
      </g>

      {/* State 4 - Add 14px left padding to align with state 3 */}
      <g className="state4">
        <path
          fillRule="evenodd"
          clipRule="evenodd"
          d="M56 42H77V21H70V35H63V28H56V7H63V0H91V7H98V21H105V35H91V56H84V77H70V63H63V56H42V63H35V77H21V42H28V35H56V42ZM84 21H91V14H84V21Z"
          fill={fillColor}
        />
        <path d="M21 42H14V14H21V42Z" fill={fillColor} />
      </g>
    </svg>
  );
};

export default DogIcon;
